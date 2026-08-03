# coding: utf-8

import logging
import traceback
from odoo import api, fields, models
from odoo.exceptions import ValidationError
from .ebiz_charge import message_wizard
from ..tools import _year_selection_from_2000, _month_selection
import re

_logger = logging.getLogger(__name__)


def _log_token_archive(site, tokens):
    """TEMPORARY DIAGNOSTIC — remove once the archived-saved-token bug is resolved.
    Logs which code path archived which tokens, with a stack trace."""
    try:
        token_info = ', '.join(
            f"id={t.id} partner={t.partner_id.id} profile={t.ebizcharge_profile} is_card_save={t.is_card_save}"
            for t in tokens
        )
        _logger.warning(
            "[TOKEN-ARCHIVE-DIAG] site=%s archiving [%s]\nStack:\n%s",
            site, token_info, ''.join(traceback.format_stack()[-10:-1])
        )
    except Exception as exc:
        _logger.warning("[TOKEN-ARCHIVE-DIAG] site=%s failed to log: %s", site, exc)


def _delete_token_from_ebiz(ebizcharge_profile, partner_id, ebiz_charge_api):
    if ebizcharge_profile and partner_id.ebiz_profile_id:
        ebiz = ebiz_charge_api.get_ebiz_charge_obj(instance=partner_id.ebiz_profile_id)
        return ebiz.client.service.DeleteCustomerPaymentMethodProfile(**{
            'securityToken': ebiz._generate_security_json(),
            'customerToken': partner_id.ebizcharge_customer_token,
            'paymentMethodId': ebizcharge_profile
        })
    return True

def check_profile(ebizcharge_profile, partner_id, ebiz_charge_api):
    if partner_id.ebiz_profile_id:
        instance = partner_id.ebiz_profile_id
        ebiz = ebiz_charge_api.get_ebiz_charge_obj(instance=instance)
        try:
            resp = ebiz.client.service.GetCustomerPaymentMethodProfile(**{
                'securityToken': ebiz._generate_security_json(),
                'customerToken': partner_id.ebizcharge_customer_token,
                'paymentMethodId': ebizcharge_profile
            })
            if resp:
                return True
        except Exception:
            return False
    return False


class PaymentToken(models.Model):
    _inherit = 'payment.token'

    @api.model
    def year_selection(self):
        return _year_selection_from_2000()

    @api.model
    def month_selection(self):
        return _month_selection()

    @api.model
    def get_card_type_selection(self):
        icons_dict = {
            'A': 'American Express',
            'DS': 'Discover',
            'M': 'Master Card',
            'V': 'VISA'
        }
        return list(icons_dict.items())

    @property
    def _rec_names_search(self):
        return ['display_name']

    ebizcharge_profile = fields.Char(string='EBizCharge Profile ID', help='This contains the unique reference '
                                                                          'for this partner/payment token combination in the Authorize.net backend')
    account_holder_name = fields.Char(string='Account Holder Name *')
    card_number = fields.Char(string='Card Number')

    @api.constrains('ebizcharge_profile')
    def _constrains_ebizcharge_profile(self):
        if self.env.context.get('donot_sync'):
            return
        for line in self:
            if line.partner_id and line.ebizcharge_profile:
                line.partner_id.sync_to_ebiz()
                instance = line.partner_id.ebiz_profile_id
                ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
                try:
                    resp = ebiz.client.service.GetCustomerPaymentMethodProfile(**{
                        'securityToken': ebiz._generate_security_json(),
                        'customerToken': line.partner_id.ebizcharge_customer_token,
                        'paymentMethodId': line.ebizcharge_profile
                    })
                    if resp:
                        method = self.env.ref('payment_ebizcharge_crm.payment_method_ebizcharge').id
                        if resp['MethodType'] == 'cc':
                            if resp['CardType']:
                                line.write({'card_type': resp['CardType'],
                                            'payment_method_icon': method,
                                            'payment_method_id': method,
                                            'card_number': resp['CardNumber'],
                                            'card_number_ecom': "ending in " + str(
                                                re.split('(\d+)', resp['CardNumber'])[1])})
                        else:
                            line.write(
                                {'card_type': resp['CardType'], 'payment_method_id': method,
                                 'account_number': resp['Account'],
                                 'account_number_ecom': resp['AccountType'].capitalize() + " ending in " + str(
                                     re.split('(\d+)', resp['Account'])[1])})
                except Exception as e:
                    _logger.warning("PaymentMethodProfile: %s", e)

    card_expiration = fields.Date(string='Expiration Date')
    card_exp_year = fields.Selection(year_selection, string='Expiration Year')
    card_exp_month = fields.Selection(month_selection, string='Expiration Month')
    avs_street = fields.Char(string="Billing Address *")
    avs_zip = fields.Char(string='Zip / Postal Code *')
    card_code = fields.Char(string='Security Code')
    card_type = fields.Char(string='card type')
    is_default = fields.Boolean(string='Is Default')
    ebiz_internal_id = fields.Char(string="EBizCharge Internal Id")
    token_type = fields.Selection([('credit', 'Credit Card'), ('ach', 'ACH')], string="Token Type", default="credit")
    account_number = fields.Char(string="Account Number")
    account_type = fields.Selection([('Checking', 'Checking'), ('Savings', 'Savings')], string="Account Type *",
                                    default="Checking")
    routing = fields.Char(string='Routing Number', )
    card_exp_date = fields.Char(string='Card Expiration Date', compute="_compute_card_exp_date")
    user_id = fields.Many2one('res.users')
    payment_method_icon = fields.Many2one('payment.method')
    image = fields.Binary(string="Image", related="payment_method_icon.image")
    card_number_ecom = fields.Char(string='Card Number Ecom')
    account_number_ecom = fields.Char(string='Card Number Acc')
    ebiz_profile_id = fields.Many2one('ebizcharge.instance.config')
    is_card_save = fields.Boolean()

    @api.depends('token_type', 'card_exp_month', 'card_exp_year')
    def _compute_card_exp_date(self):
        for card in self:
            if card.token_type == "credit":
                card.card_exp_date = f"{card.card_exp_month}/{card.card_exp_year}"
            else:
                card.card_exp_date = ""

    @api.model
    def get_payment_token_information(self, pm_id):
        ebiz = self.browse(pm_id)
        return ebiz.sudo().read()[0]

    @api.model
    def default_get(self, fields_list):
        res = super(PaymentToken, self).default_get(fields_list)
        if self.env.context.get('default_is_ebiz_charge'):
            res['provider_id'] = self.env['payment.provider'].search(
                [('company_id', '=', self.env.company.id), ('code', '=', 'ebizcharge')], limit=1).id
        return res

    def sync_credit_card(self):
        for profile in self:
            if profile.partner_id.ebiz_internal_id:
                profile.partner_id.sync_to_ebiz()
                instance = profile.partner_id.ebiz_profile_id or None
                ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(self.env.context.get('website'),
                                                                       instance=instance)
                if profile.ebizcharge_profile:
                    ebiz.update_customer_payment_profile(profile)
                    if profile.is_default:
                        profile.make_default()
                else:
                    res = ebiz.add_customer_payment_profile(profile)
                    last4 = profile.card_number[-4:]
                    card_number = 'XXXXXXXXXXXX%s' % last4
                    profile.with_context({'donot_sync': True}).write({
                        'ebizcharge_profile': res,
                        'provider_ref': res,
                        'card_number': card_number,
                    })
                    if profile.is_default:
                        profile.make_default()

    def sync_ach(self):
        for profile in self:
            instance = profile.partner_id.ebiz_profile_id or None
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(self.env.context.get('website'), instance=instance)
            if profile.partner_id.ebiz_internal_id:
                if profile.ebizcharge_profile:
                    resp = ebiz.update_customer_payment_profile(profile, p_type="bank")
                    if profile.is_default:
                        profile.make_default()
                    return resp
                else:
                    res = ebiz.add_customer_payment_profile(profile, p_type="bank")
                    last4 = profile.account_number[-4:]
                    account_number = self.get_asteriks(profile.account_number) + last4
                    profile.write({
                        'ebizcharge_profile': res,
                        'provider_ref': res,
                        'payment_details': 'XXXXX%s' % account_number[-4:],
                        'account_number': account_number,
                        'routing': "XXXXX%s" % profile.routing[-4:],
                    })
                    if profile.is_default:
                        profile.make_default()
                    return res

    def get_asteriks(self, number):
        return 'X' * (len(number) - 4)

    def get_token_type_label(self):
        return 'Card' if self.token_type == 'credit' else 'Bank'

    def get_encrypted_payment_details(self, number, last4):
        return self.get_asteriks(number) + last4

    def get_encrypted_name(self):
        self.ensure_one()
        card_types = self.get_card_type_selection()
        card_types = {x[0]: x[1] for x in card_types}
        payment_details = self.payment_details
        if payment_details:
            if self.card_type and self.card_type != 'Unknown':
                c_type = card_types['DS' if self.card_type not in card_types else self.card_type]
                return '%s Ending in %s (%s)' % (c_type, payment_details[-4:], self.get_token_type_label())
            elif self.account_type and self.account_number and payment_details:
                return '%s Ending in %s (%s)' % (self.account_type, payment_details[-4:], self.get_token_type_label())
        return self.display_name

    def do_syncing(self):
        try:
            for token in self:
                if not token.partner_id.ebiz_internal_id or not token.partner_id.ebizcharge_customer_token:
                    token.partner_id.sync_to_ebiz()
                if token.token_type == 'ach':
                    return token.sync_ach()
                else:
                    return token.sync_credit_card()
        except Exception as e:
            raise ValidationError(e)

    def get_card_type_dict(self, val):
        partner = self.env['res.partner'].browse(val['partner_id'])
        instance = partner.ebiz_profile_id
        ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
        resp = ebiz.client.service.GetCustomerPaymentMethodProfile(**{
            'securityToken': ebiz._generate_security_json(),
            'customerToken': partner.ebizcharge_customer_token,
            'paymentMethodId': val['ebizcharge_profile']
        })
        return resp

    def action_sync_token_to_ebiz(self):
        try:
            for profile in self:
                if profile.provider_id.id == self.env['payment.provider'].search(
                        [('company_id', '=', profile.provider_id.company_id.id), ('code', '=', 'ebizcharge')],
                        limit=1).id:
                    if not self.env.context.get('donot_sync'):
                        profile.do_syncing()
                        if not self.env.user._is_public():
                            profile.get_card_type()

        except Exception as e:
            _logger.exception(e)
            if len(e.args) == 2 and 'Invalid Card Number' in e.args[0]:
                raise ValidationError('You have entered invalid card number!')
            else:
                raise ValidationError(e)

    def token_action_archive(self):
        for token in self:
            _log_token_archive('payment_token.token_action_archive', token)
            token.write({"active": False})
            if token.sudo().check_profile(token):
                try:
                    token.sudo().delete_payment_method()
                    another_token = self.env['payment.token'].search(
                        [('ebizcharge_profile', '=', token.ebizcharge_profile),
                         ('id', '!=', token.id)])
                    if another_token:
                        another_token.with_context({'donot_sync': True}).unlink()
                except Exception as e:
                    _logger.exception(e)

    def make_default(self):
        instance = (
            self.partner_id.ebiz_profile_id
            or self.env['ebizcharge.instance.config'].search(
                [('is_valid_credential', '=', True), ('is_default', '=', True)], limit=1)
            or None
        )

        ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
        resp = ebiz.client.service.SetDefaultCustomerPaymentMethodProfile(**{
            'securityToken': ebiz._generate_security_json(),
            'customerToken': self.partner_id.ebizcharge_customer_token,
            'paymentMethodId': self.ebizcharge_profile
        })
        profile = self.partner_id.payment_token_ids.filtered(lambda x: x.is_default)
        if profile:
            profile -= self
            if profile:
                profile.with_context({'donot_sync': True}).write({'is_default': False})
        self.with_context({'donot_sync': True}).write({'is_default': True})
        return resp

    def _ebiz_check_update_sync(self, values):
        update_check_fields = {"account_holder_name", "card_number", "card_exp_year", "card_exp_month", "avs_street",
                               "avs_zip", "card_code", "account_type", "is_default"}
        return bool(update_check_fields.intersection(values))

    def check_profile(self, token):
        if token.partner_id.ebiz_profile_id:
            instance = token.partner_id.ebiz_profile_id
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
            try:
                resp = ebiz.client.service.GetCustomerPaymentMethodProfile(**{
                    'securityToken': ebiz._generate_security_json(),
                    'customerToken': token.partner_id.ebizcharge_customer_token,
                    'paymentMethodId': token.ebizcharge_profile
                })
                if resp:
                    return True
            except Exception:
                return False
        return False

    def unlink(self):
        prepare_payload_tokens = []
        for token in self:
            prepare_payload_tokens.append({
                'ebizcharge_profile': token.ebizcharge_profile,
                'partner_id': token.partner_id,
                'provider_code': token.sudo().provider_id.code,
                'id': token.id,
            })
        result = super(PaymentToken, self).unlink()
        if not self.env.context.get('donot_sync') and result:
            for token in prepare_payload_tokens:
                if token.get('provider_code') == 'ebizcharge':
                    if check_profile(token.get('ebizcharge_profile'), token.get('partner_id'), self.env['ebiz.charge.api']):
                        try:
                            _delete_token_from_ebiz(token.get('ebizcharge_profile'), token.get('partner_id'), self.env['ebiz.charge.api'])
                            other_tokens = self.env['payment.token'].sudo().search(
                                [('ebizcharge_profile', '=', token.get('ebizcharge_profile')),
                                 ('id', '!=', token.get('id'))])
                            if other_tokens:
                                _log_token_archive('payment_token.unlink (same-profile cascade)', other_tokens)
                                other_tokens.write({'active': False})
                            token.get('partner_id').with_context({'donot_sync': True}).ebiz_get_payment_methods()
                        except Exception as e:
                            _logger.exception(e)
        return result

    def delete_payment_method(self):
        if self.ebizcharge_profile and self.partner_id.ebiz_profile_id:
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=self.partner_id.ebiz_profile_id)
            return ebiz.client.service.DeleteCustomerPaymentMethodProfile(**{
                'securityToken': ebiz._generate_security_json(),
                'customerToken': self.partner_id.ebizcharge_customer_token,
                'paymentMethodId': self.ebizcharge_profile
            })
        return True

    def delete_token(self):
        text = "Are you sure you want to delete this payment method?"
        wizard = self.env['wizard.token.delete.confirmation'].create({"record_id": self.id,
                                                                      "record_model": self._name,
                                                                      "text": text})
        action = self.env.ref('payment_ebizcharge_crm.wizard_delete_token_action').read()[0]
        action['res_id'] = wizard.id
        return action

    def open_edit(self):
        if self.token_type == "credit":
            title = 'Edit Credit Card'
            view_id = self.env.ref('payment_ebizcharge_crm.payment_token_credit_card_view_form').id
        else:
            title = 'Edit Bank Account'
            view_id = self.env.ref('payment_ebizcharge_crm.payment_token_ach_view_form').id
        self.card_code = False
        return {
            'name': title,
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'payment.token',
            'res_id': self.id,
            'view_id': view_id,
            'type': 'ir.actions.act_window',
            'target': 'new',
            'context': self.env.context
        }

    def update_payment_token(self):
        try:
            if self.is_default:
                check = self.partner_id.payment_token_ids.filtered(
                    lambda x: x.is_default and x.id != self.id and x.provider_id.code == 'ebizcharge')
                if check:
                    self.is_default = False
                    message = 'A payment method is already selected as default! Do you want to mark this one as default instead?'
                    wiz = self.env['wizard.validate.default'].create(
                        {'token_id': self.id, 'text': message, 'default_token_id': check[0].id})
                    action = self.env.ref('payment_ebizcharge_crm.action_wizard_validate_default').read()[0]
                    action['res_id'] = wiz.id
                    return action
                else:
                    self.make_default()

            return message_wizard('Record has been successfully updated!')

        except Exception as e:
            _logger.exception(e)
            raise ValidationError(e)

    def get_card_type(self):
        ebiz_obj = self.env['ebiz.charge.api']
        for card in self:
            instance = card.partner_id.ebiz_profile_id or None

            if not instance and 'website' in self.env.context:
                ebiz = ebiz_obj.get_ebiz_charge_obj(website_id=self.env.context.get('website'))
            else:
                ebiz = ebiz_obj.get_ebiz_charge_obj(instance=instance)
            resp = ebiz.client.service.GetCustomerPaymentMethodProfile(**{
                'securityToken': ebiz._generate_security_json(),
                'customerToken': card.partner_id.ebizcharge_customer_token,
                'paymentMethodId': card.ebizcharge_profile
            })
            if resp:
                if resp['MethodType'] == 'cc':
                    if resp['CardType']:
                        odoo_image = self.env.ref('payment_ebizcharge_crm.payment_method_ebizcharge').id
                        card.write({'card_type': resp['CardType'],
                                    'payment_method_icon': odoo_image,
                                    'card_number': resp['CardNumber'],
                                    'card_number_ecom': "ending in " + str(re.split('(\d+)', resp['CardNumber'])[1])})
                else:
                    card.write({'card_type': resp['CardType'],
                                'account_number': resp['Account'],
                                'routing': resp['Routing'],
                                'account_number_ecom': resp['AccountType'].capitalize() + " ending in " + str(
                                    re.split('(\d+)', resp['Account'])[1])})

    @api.depends('payment_details', 'create_date', 'card_type', 'token_type')
    def _compute_display_name(self):
        for token in self:
            if token.provider_id.code == 'ebizcharge':
                payment_details = token.get_encrypted_name()
                if token.is_default:
                    payment_details = (payment_details or "") + ' (Default)'
                token.display_name = payment_details
            else:
                token.display_name = token._build_display_name()

    @api.model
    def _name_search(self, name='', domain=None, operator='ilike', limit=100, order=None):
        domain = list(domain or [])

        partner_id = next(
            (arg[-1] for arg in domain if isinstance(arg, (list, tuple)) and len(arg) == 3 and arg[0] == 'partner_id'),
            None
        )
        if partner_id:
            token_exists = self.search([('user_id', '=', self.env.user.id), ('partner_id', '=', partner_id)], limit=1)
            if not token_exists:
                partner = self.env['res.partner'].browse(partner_id).exists()
                if partner:
                    partner.sudo().with_context(donot_sync=True).ebiz_get_payment_methods()

        journal_id = next(
            (arg[-1] for arg in domain if isinstance(arg, (list, tuple)) and len(arg) == 3 and arg[0] == 'provider_id.journal_id'),
            None
        )
        if journal_id:
            if self.env['account.journal'].browse(journal_id).name == 'EBizCharge':
                domain.append(('create_uid', 'in', [self.env.user.id]))

        return super()._name_search(name, domain, operator, limit, order)
