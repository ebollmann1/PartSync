# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging
from datetime import datetime
import re
from .ebiz_charge import message_wizard

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _get_default_ebiz_auto_sync(self):
        return self.ebiz_profile_id.ebiz_auto_sync_customer if self.ebiz_profile_id else False

    def _compute_ebiz_auto_sync(self):
        self.ebiz_auto_sync = False

    def get_default_ebiz(self):
        profiles = self.env['ebizcharge.instance.config'].search(
            [('is_active', '=', True), '|', ('company_ids', '=', False),
             ('company_ids', 'in', self.env.context.get('allowed_company_ids'))]).ids
        return profiles

    def get_default_company(self):
        companies = self.env.context.get('allowed_company_ids')
        return companies

    ebiz_ach_tokens = fields.One2many('payment.token', string='EBizCharge ACH', compute="_compute_ach", copy=False)
    ebiz_credit_card_ids = fields.One2many('payment.token', string='EBizCharge Credit Card',
                                           compute="_compute_credit_card", copy=False)
    ebiz_internal_id = fields.Char(string='Customer Internal Id', copy=False)
    ebizcharge_customer_token = fields.Char(string='Customer Token', copy=False)
    webform_url = fields.Char(string='Url for Web form', required=False)
    ebiz_auto_sync = fields.Boolean(compute="_compute_ebiz_auto_sync", default=_get_default_ebiz_auto_sync)
    sync_status = fields.Char(string="EBizCharge Upload Status", compute="_compute_sync_status")
    ebiz_customer_internal_id = fields.Char('EBiz Customer Internal ID')
    ebiz_customer_id = fields.Char('EBiz Customer ID')
    request_payment_method_sent = fields.Boolean('EBiz Request payment', default=False)
    sync_response = fields.Char(string="Sync Status", copy=False)
    last_sync_date = fields.Datetime(string="Upload Date & Time", copy=False)
    payment_token_ach_count = fields.Integer('Count Payment Token', compute='_compute_payment_ach_token_count')
    ach_functionality_hide = fields.Boolean(compute="check_if_merchant_needs_avs_validation", default=False)
    card_functionality_hide = fields.Boolean(default=False)
    ebiz_profile_id = fields.Many2one('ebizcharge.instance.config', copy=False)
    ebiz_profile_ids = fields.Many2many('ebizcharge.instance.config', compute='compute_ebiz_profiles',
                                        string="Profiles", default=get_default_ebiz)
    ebiz_company_ids = fields.Many2many('res.company', compute='compute_company', default=get_default_company)

    @api.depends('ebiz_profile_id', 'company_id')
    def compute_ebiz_profiles(self):
        profile_obj = self.env['ebizcharge.instance.config']
        allowed_company_ids = self.env.context.get('allowed_company_ids') or []
        for partner in self:
            if partner.company_id:
                profiles = profile_obj.search(
                    [('is_active', '=', True), ('is_default', '=', False), '|', ('company_ids', '=', False),
                     ('company_ids', 'in', partner.company_id.ids)])
            elif partner.ebiz_profile_id:
                profiles = profile_obj.search(
                    [('is_active', '=', True), '|', '|', ('id', '=', partner.ebiz_profile_id.id),
                     ('company_ids', '=', False), ('company_ids', 'in', allowed_company_ids)])
            else:
                profiles = profile_obj.search(
                    [('is_active', '=', True), '|', ('company_ids', '=', False),
                     ('company_ids', 'in', allowed_company_ids)])
            partner.ebiz_profile_ids = profiles

    @api.depends('ebiz_profile_id', 'company_id')
    def compute_company(self):
        profile_obj = self.env['ebizcharge.instance.config']
        for partner in self:
            if partner.ebiz_profile_id and partner.ebiz_profile_id.is_default:
                companies = []
            elif partner.ebiz_profile_id:
                companies = partner.ebiz_profile_id.company_ids.filtered(
                    lambda i: i.id in self.env.context.get('allowed_company_ids')).ids
                if not partner.ebiz_profile_id.company_ids:
                    existing_companies = profile_obj.search(
                        [('is_active', '=', True)]).mapped(
                        'company_ids').ids
                    companies = self.env['res.company'].search([('id', 'not in', existing_companies), (
                        'id', 'in', self.env.context.get('allowed_company_ids'))])
            elif partner.company_id:
                companies = profile_obj.search(
                    [('is_active', '=', True), '|', ('company_ids', '=', False),
                     ('company_ids', 'in', partner.company_id.ids)]).mapped('company_ids').ids
            else:
                companies = self.env.context.get('allowed_company_ids')
            partner.ebiz_company_ids = companies

    @api.onchange('ebiz_profile_id')
    def onchange_ebiz_profile(self):
        if len(self.ebiz_profile_id.company_ids) == 1:
            self.company_id = self.ebiz_profile_id.company_ids[0].id
        else:
            self.company_id = False

    @api.constrains('ebiz_profile_id')
    def check_ebiz_profile(self):
        from .payment_token import _log_token_archive
        if self.ebiz_credit_card_ids:
            _log_token_archive('res_partner.check_ebiz_profile (credit cards)', self.ebiz_credit_card_ids)
        if self.ebiz_ach_tokens:
            _log_token_archive('res_partner.check_ebiz_profile (ach)', self.ebiz_ach_tokens)
        self.ebiz_credit_card_ids.write({"active": False})
        self.ebiz_ach_tokens.write({"active": False})
        self.sync_status = 'Pending'
        self.ebiz_customer_internal_id = ''
        self.ebiz_customer_id = ''
        self.ebiz_internal_id = ''
        self.ebizcharge_customer_token = ''

    @api.onchange('company_id')
    def onchange_ebiz_company(self):
        ebiz_profile = self.env['ebizcharge.instance.config'].search(
                [('is_active', '=', True), ('company_ids', 'in', self.company_id.ids)], limit=1)
        if ebiz_profile:
            self.ebiz_profile_id = ebiz_profile.id

    @api.depends('ebiz_profile_id')
    def check_if_merchant_needs_avs_validation(self):
        self.ach_functionality_hide = self.ebiz_profile_id.merchant_data if self.ebiz_profile_id else False
        self.card_functionality_hide = self.ebiz_profile_id.allow_credit_card_pay if self.ebiz_profile_id else False

    def get_default_token(self):
        for token in self.payment_token_ids.filtered(lambda r: r.provider_id.code == 'ebizcharge'):
            if token.is_default:
                return token
        return None

    @api.depends('payment_token_ids')
    def _compute_payment_ach_token_count(self):
        groups = self.env['payment.token']._read_group(
            domain=[('partner_id', 'in', self.ids), ('token_type', '=', 'ach')],
            groupby=['partner_id'],
            aggregates=['__count'],
        )
        mapped_data = {partner.id: count for partner, count in groups}
        for partner in self:
            partner.payment_token_ach_count = mapped_data.get(partner.id, 0)

    @api.depends('payment_token_ids')
    def _compute_payment_token_count(self):
        groups = self.env['payment.token']._read_group(
            domain=[('partner_id', 'in', self.ids), ('token_type', '=', 'credit')],
            groupby=['partner_id'],
            aggregates=['__count'],
        )
        mapped_data = {partner.id: count for partner, count in groups}
        for partner in self:
            partner.payment_token_count = mapped_data.get(partner.id, 0)

    @api.depends('active', 'customer_rank', 'ebiz_internal_id')
    def _compute_sync_status(self):
        for cus in self:
            if not cus.active:
                cus.sync_status = "Archive"
            elif cus.ebiz_internal_id:
                cus.sync_status = "Synchronized"
            else:
                cus.sync_status = "Pending"

    @api.depends('payment_token_ids.token_type')
    def _compute_credit_card(self):
        for partner in self:
            partner.ebiz_credit_card_ids = partner.payment_token_ids.filtered(lambda x: x.token_type == 'credit' and x.provider_code == 'ebizcharge')

    @api.depends('payment_token_ids.token_type')
    def _compute_ach(self):
        for partner in self:
            partner.ebiz_ach_tokens = partner.payment_token_ids.filtered(lambda x: x.token_type == 'ach' and x.provider_code == 'ebizcharge')

    @api.model_create_multi
    def create(self, vals_list):
        res = super(ResPartner, self).create(vals_list)
        for partner, vals in zip(res, vals_list):
            if partner.ebiz_profile_id:
                if partner.customer_rank > 0 and not partner.ebiz_internal_id:
                    partner.sync_to_ebiz(instance=partner.ebiz_profile_id)
            else:
                if 'portal_user' in self.env.context and 'website_id' in self.env.context:
                    instance = self.env['ebizcharge.instance.config'].sudo().search(
                         [('is_website', '=', True), ('website_ids', 'in', [self.env.context['website_id']]),
                          ('is_active', '=', True)], limit=1)
                else:
                    instance = self.env['ebizcharge.instance.config'].sudo().search(
                        [('is_valid_credential', '=', True), ('is_active', '=', True), ('is_default', '=', True)], limit=1)
                if instance:
                    vals['customer_rank'] = 1
                    vals['ebiz_profile_id'] = instance.id
                    if partner.customer_rank > 0 and not partner.ebiz_internal_id:
                        partner.sync_to_ebiz(instance=instance)
        return res

    def sync_to_ebiz_ind(self):
        self.sync_to_ebiz()
        return message_wizard('Customer uploaded successfully!')

    def sync_to_ebiz(self, time_sample=None, instance=None):
        self.ensure_one()
        if not instance:
            instance = (
                self.ebiz_profile_id
                or self.env['ebizcharge.instance.config'].search(
                    [('is_valid_credential', '=', True), ('is_default', '=', True)], limit=1)
                or None
            )
        if not self.ebiz_profile_id:
            self.ebiz_profile_id = instance
        if not instance and 'website' not in self.env.context:
            raise ValidationError('Please attach profile on customer record or set one of profile to default.')
        web = self.env['ir.module.module'].sudo().search([('name', '=', 'website_sale'), ('state', 'in', ['installed', 'to upgrade', 'to remove'])])
        ebiz_obj = self.env['ebiz.charge.api']
        if web:
            ebiz = ebiz_obj.get_ebiz_charge_obj(
                website_id=self.website_id.id or self.env.context.get('website') or self.env.context.get('website_id') if hasattr(
                    self, 'website_id') or 'website' not in self.env.context else None,
                instance=instance)
        else:
            ebiz = ebiz_obj.get_ebiz_charge_obj(instance=instance)

        update_params = {}
        if self.ebiz_internal_id:
            resp = ebiz.update_customer(self)
        else:
            resp = ebiz.add_customer(self)
            if resp['ErrorCode'] == 0:
                update_params = {
                    'ebiz_internal_id': resp['CustomerInternalId'],
                    'ebiz_customer_id': resp['CustomerId']
                }
        self.create_customer_log(resp)
        token = ebiz.get_customer_token(self.id)
        update_params['ebizcharge_customer_token'] = token
        update_params.update({'last_sync_date': fields.Datetime.now(),
                              'sync_response': 'Success' if resp['ErrorCode'] in [0, 2] else resp['Error'],
                              'ebiz_internal_id': resp['CustomerInternalId'],
                              'ebiz_customer_id': resp['CustomerId']})
        self.write(update_params)
        return resp

    def create_customer_log(self, resp):
        self.env['logs.of.customers'].create({
            'customer_id': self.id,
            'name': self.name,
            'street': self.street or "",
            'email_id': self.email or "",
            'customer_phone': self.phone or "",
            'sync_status': 'Success' if resp['ErrorCode'] in [0, 2] else resp['Error'],
            'last_sync_date': datetime.now(),
            'user_id': self.env.user.id,
        })

    def view_logs(self):
        return {
            'name': (_('Customer Logs')),
            'view_type': 'form',
            'res_model': 'customer.logs',
            'target': 'new',
            'view_id': False,
            'view_mode': 'list,pivot,form',
            'type': 'ir.actions.act_window',
        }

    def _build_customer_sync_result(self, partners):
        resp_lines = []
        success = 0
        failed = 0
        for partner in partners:
            if partner.customer_rank > 0:
                resp_line = {'customer_name': partner.name, 'customer_id': partner.id}
                try:
                    resp = partner.sync_to_ebiz()
                    resp_line['record_message'] = resp['Error'] or resp['Status']
                except Exception as e:
                    _logger.exception(e)
                    resp_line['record_message'] = str(e)
                if resp_line['record_message'] in ('Success', 'Record already exists'):
                    success += 1
                else:
                    failed += 1
                resp_lines.append(fields.Command.create(resp_line))
        wizard = self.env['wizard.multi.sync.message'].create({
            'name': 'customers', 'customer_lines_ids': resp_lines,
            'success_count': success, 'failed_count': failed, 'total': len(partners),
        })
        action = self.env.ref('payment_ebizcharge_crm.wizard_multi_sync_message_action').read()[0]
        action['context'] = self.env.context
        action['res_id'] = wizard.id
        return action

    def sync_multi_customers(self):
        return self._build_customer_sync_result(self)

    def sync_multi_customers_from_upload_customers(self, partner_ids):
        return self._build_customer_sync_result(self.env['res.partner'].browse(partner_ids).exists())

    def add_new_card(self):
        if self.customer_rank > 0 and not self.ebiz_internal_id:
            self.sync_to_ebiz()
        wizard = self.env['wizard.add.new.card'].create({'partner_id': self.id,
                                                         'card_account_holder_name': self.name,
                                                         'card_avs_street': self.street,
                                                         'card_avs_zip': self.zip})
        action = self.env.ref('payment_ebizcharge_crm.action_wizard_add_new_card').read()[0]
        action['res_id'] = wizard.id
        return action

    def add_new_ach(self):
        if self.customer_rank > 0 and not self.ebiz_internal_id:
            self.sync_to_ebiz()
        wizard = self.env['wizard.add.new.ach'].create({'partner_id': self.id,
                                                        'ach_account_holder_name': self.name})
        action = self.env.ref('payment_ebizcharge_crm.action_wizard_add_new_ach').read()[0]
        action['res_id'] = wizard.id
        return action

    def ebiz_get_payment_methods(self):
        try:
            if self.sync_status == 'Synchronized' and self.ebiz_profile_id:
                instance = self.ebiz_profile_id
                get_merchant_data = self.ebiz_profile_id.merchant_data
                get_allow_credit_card_pay = self.ebiz_profile_id.allow_credit_card_pay

                if not instance and 'website' not in self.env.context:
                    raise UserError('Please try with new card or bank account')
                ebiz_obj = self.env['ebiz.charge.api']
                if 'website' in self.env.context:
                    ebiz = ebiz_obj.get_ebiz_charge_obj(website_id=self.env.context.get('website'), instance=instance)
                else:
                    ebiz = ebiz_obj.get_ebiz_charge_obj(instance=instance)
                methods = ebiz.client.service.GetCustomerPaymentMethodProfiles(
                    **{'securityToken': ebiz._generate_security_json(),
                       'customerToken': self.ebizcharge_customer_token})

                if not methods:
                    from .payment_token import _log_token_archive
                    ebiz_tokens_to_archive = self.payment_token_ids.filtered(lambda r: r.provider_id.code == 'ebizcharge')
                    if ebiz_tokens_to_archive:
                        _log_token_archive('res_partner.ebiz_get_payment_methods (no methods returned)', ebiz_tokens_to_archive)
                    ebiz_tokens_to_archive.write({"active": False})
                    return

                odoo_image = self.env.ref('payment_ebizcharge_crm.payment_method_ebizcharge').id
                company_id = self.company_id.id if self.company_id else self.env.company.id
                provider_id = self.env['payment.provider'].search(
                    [('company_id', '=', company_id), ('code', '=', 'ebizcharge')], limit=1).id

                for method in methods:
                    if method['MethodType'] == 'cc':
                        if get_allow_credit_card_pay:
                            card = self.payment_token_ids.filtered(lambda x: x.ebizcharge_profile == method['MethodID'])
                            exp = method['CardExpiration'].split('-')
                            params = {
                                "account_holder_name": method['AccountHolderName'],
                                "card_type": method['CardType'],
                                "card_number": method['CardNumber'],
                                "payment_details": method['CardNumber'],
                                "card_exp_year": exp[0],
                                "card_exp_month": str(int(exp[1])),
                                "avs_street": method['AvsStreet'],
                                "avs_zip": method['AvsZip'],
                                "partner_id": self.id,
                                "is_default": method['SecondarySort'] == "0",
                                "provider_ref": method['MethodID'],
                                "ebizcharge_profile": method['MethodID'],
                                "is_card_save": True,
                                "active": True,
                                'payment_method_icon': odoo_image,
                                'payment_method_id': odoo_image,
                                'ebiz_profile_id': instance.id,
                                'card_number_ecom': "ending in " + str(re.split('(\\d+)', method['CardNumber'])[1])
                            }
                            if card:
                                card.write(params)
                            else:
                                params.update({
                                    "user_id": self.env.user.id,
                                    'provider_id': provider_id,
                                })
                                self.env['payment.token'].sudo().create(params)
                    else:
                        if get_merchant_data:
                            bank = self.payment_token_ids.filtered(
                                lambda x: x.ebizcharge_profile == method[
                                    'MethodID'] and x.company_id.id == self.env.company.id)
                            last_ecom_alias = ''
                            if bank and bank.account_number:
                                last_ecom_alias = bank.account_number.replace('X', '')
                            params = {
                                'account_holder_name': method['AccountHolderName'],
                                'payment_details': method['Account'],
                                'account_number': method['Account'],
                                'account_type': method['AccountType'].capitalize() if method['AccountType'].capitalize() in ('Checking', 'Savings') else 'Checking',
                                'routing': method['Routing'],
                                'is_default': method['SecondarySort'] == "0",
                                'ebiz_internal_id': method['MethodID'],
                                'partner_id': self.id,
                                'is_card_save': True,
                                'payment_method_id': odoo_image,
                                'provider_ref': method['MethodID'],
                                'ebizcharge_profile': method['MethodID'],
                                'token_type': 'ach',
                                'account_number_ecom': method['AccountType'].capitalize() + " ending in " + str(
                                    last_ecom_alias)
                            }
                            if bank:
                                bank.write(params)
                            else:
                                params.update({
                                    "user_id": self.env.user.id,
                                    'provider_id': provider_id,
                                })
                                self.env['payment.token'].sudo().create(params)

                self.write({'request_payment_method_sent': False})

                from .payment_token import _log_token_archive
                active_method_ids = {m['MethodID'] for m in methods}
                for odoo_token_id in self.payment_token_ids.filtered(lambda r: r.provider_id.code == 'ebizcharge'):
                    if odoo_token_id.ebizcharge_profile not in active_method_ids:
                        _log_token_archive(
                            f"res_partner.ebiz_get_payment_methods (profile {odoo_token_id.ebizcharge_profile!r} not in EBiz response {active_method_ids!r})",
                            odoo_token_id,
                        )
                        odoo_token_id.write({"active": False})
        except Exception as e:
            _logger.exception(e)
            raise ValidationError(e)

    @api.model
    def cron_load_payment_methods(self):
        partners = self.search([('request_payment_method_sent', '=', True)])
        for partner in partners:
            partner.with_context(donot_sync=True).ebiz_get_payment_methods()

    def write(self, values):
        ret = super(ResPartner, self).write(values)
        for partner in self:
            if 'ebiz_profile_id' in values:
                instance = self.env['ebizcharge.instance.config'].browse(values['ebiz_profile_id']).exists()
                partner.sync_to_ebiz(instance=instance)
                partner.with_context({'donot_sync': True}).ebiz_get_payment_methods()
            elif partner._ebiz_check_update_sync(values) and partner.ebiz_internal_id:
                partner.sync_to_ebiz()
        return ret

    def ebiz_request_payment_method(self):
        try:
            if self.customer_rank > 0 and not self.ebiz_internal_id:
                self.sync_to_ebiz()
            wiz = self.env['wizard.ebiz.request.payment.method'].with_context({'partner': self.id, 'profile': self.ebiz_profile_id.id}).create(
                {'partner_id': [fields.Command.set([self.id])], 'email': self.email, 'ebiz_profile_id': self.ebiz_profile_id.id})
            action = self.env.ref('payment_ebizcharge_crm.action_wizard_ebiz_request_payment_method').read()[0]
            action['res_id'] = wiz.id
            action['context'] = {'partner': self.id, 'profile': self.ebiz_profile_id.id}
            return action
        except Exception as e:
            raise ValidationError(e)

    def refresh_payment_methods(self, ecom_side=None):
        self.with_context({'donot_sync': True}).ebiz_get_payment_methods()
        if not ecom_side:
            return message_wizard('Payment methods are up to date!')

    def _ebiz_check_update_sync(self, values):
        update_fields = {"name", "company_name", "phone", "mobile", "email", "website",
                         "street", "street2", "state_id", "zip", "city", "country_id", "company_type", "parent_id"}
        return bool(update_fields.intersection(values))

    def request_payment_methods_bulk(self):
        try:
            if len(self.ebiz_profile_id.ids) > 1:
                raise UserError('Please select customers with same EBizCharge Profile.')
            customer_ids = []
            self.env['email.recipients'].search([]).unlink()
            for customer in self:
                if customer.ebiz_internal_id:
                    recipient = self.env['email.recipients'].create({
                        'partner_id': customer.id,
                        'email': customer.email
                    })
                    customer_ids.append(recipient.id)
            profile = self[:1].ebiz_profile_id
            payment_type = 'BOTH'
            is_read_type = False
            if profile:
                if profile.merchant_data and profile.allow_credit_card_pay:
                    payment_type = 'BOTH'
                elif profile.allow_credit_card_pay:
                    payment_type = 'CC'
                    is_read_type = True
                elif profile.merchant_data:
                    payment_type = 'ACH'
                    is_read_type = True

                return {'type': 'ir.actions.act_window',
                        'name': _('Request Payment Method'),
                        'res_model': 'wizard.ebiz.request.payment.method.bulk',
                        'target': 'new',
                        'view_mode': 'form',
                        'view_type': 'form',
                        'context': {
                            'default_partner_id': [fields.Command.set(customer_ids)],
                            'default_ebiz_profile_id': profile.id,
                            'default_is_read_type': is_read_type,
                            'selection_check': 1,
                        }}
            else:
                raise UserError('Please select the EBizcharge Merchant account over customer profile!')
        except Exception as e:
            raise ValidationError(e)

    def transaction_details(self):
        return {
            'OrderID': "Token",
            'Invoice': "Token",
            'PONum': "Token",
            'Description': 'description',
            'Amount': 0.05,
            'Tax': 0,
            'Shipping': 0,
            'Discount': 0,
            'Subtotal': 0.05,
            'AllowPartialAuth': False,
            'Tip': 0,
            'NonTax': True,
            'Duty': 0
        }
