# -*- coding: utf-8 -*-
from odoo import models, fields, api, _, SUPERUSER_ID
from odoo.exceptions import ValidationError, UserError
from odoo.tools.float_utils import float_compare
import logging
from markupsafe import Markup
from datetime import datetime , timedelta
from .ebiz_charge import message_wizard
from odoo.addons.payment_ebizcharge_crm.tools import _prepare_billing_address, _transaction_lines
_logger = logging.getLogger(__name__)


class SaleAdvancePaymentInv(models.TransientModel):
    _inherit = 'sale.advance.payment.inv'

    is_pay_link = fields.Boolean(string='Pay Link')

    @api.model
    def _default_get_is_website_order(self):
        web = self.env['ir.module.module'].sudo().search(
            [('name', '=', 'website_sale'), ('state', 'in', ['installed', 'to upgrade', 'to remove'])])
        if web and self.env.context.get('active_model') == 'sale.order' and self.env.context.get('active_id', False):
            sale_order = self.env['sale.order'].browse(self.env.context.get('active_id'))
            return bool(sale_order.website_id)
        return False

    is_website_order = fields.Boolean("Is Website Order", default=_default_get_is_website_order)

    @api.onchange('is_pay_link')
    def onchange_sale_order_ids(self):
        for line in self:
            pay_link = False
            for so in self.sale_order_ids:
                if so.partner_id.ebiz_profile_id:
                    ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=so.partner_id.ebiz_profile_id)
                    filters_list = [{'FieldName': 'InvoiceNumber', 'ComparisonOperator': 'eq', 'FieldValue': so.name}]
                    today = datetime.now()
                    end = today + timedelta(days=1)
                    start = today + timedelta(days=-365)
                    received_payments = ebiz.client.service.SearchEbizWebFormReceivedPayments(**{
                        'securityToken': ebiz._generate_security_json(),
                        'fromPaymentRequestDateTime': str(start.date()),
                        'toPaymentRequestDateTime': str(end.date()),
                        'start': 0,
                        'limit': 10000,
                        "filters": {'SearchFilter': filters_list},
                    })
                    if not received_payments and so.save_payment_link:
                        pay_link = True
            line.is_pay_link = pay_link


class SaleOrderInh(models.Model):
    _inherit = 'sale.order'

    def _get_default_ebiz_auto_sync(self):
        profile = self.partner_id.ebiz_profile_id
        return profile.ebiz_auto_sync_sale_order if profile else False

    ebiz_internal_id = fields.Char('Ebiz Internal Id', copy=False)
    is_pre_auth = fields.Boolean(string='Pre-Auth', compute='_compute_pre_auth')
    ebiz_amount_residual = fields.Float(string='EBiz Amount Residual', compute='_compute_pre_auth')
    ebiz_order_amount_residual = fields.Float(string='EBizz Amount Residual', compute='_compute_order_pre_auth')
    ebiz_auto_sync = fields.Boolean(compute="_compute_ebiz_auto_sync", default=_get_default_ebiz_auto_sync)
    done_transaction_ids = fields.Many2many('payment.transaction', compute='_compute_done_transaction_ids',
                                            string='Authorized Transaction', copy=False, readonly=True)

    payment_internal_id = fields.Char(string='EBiz Email Response', copy=False)
    ebiz_transaction_ref = fields.Char('EBiz Transaction Ref', compute="_compute_trans_ref")
    is_invoice_paid = fields.Boolean(compute="_compute_invoice_payment_status")
    sync_status = fields.Char(string="EBizCharge Upload Status", compute="_compute_sync_status")
    sync_response = fields.Char(string="Sync Status", copy=False)
    last_sync_date = fields.Datetime(string="Upload Date & Time", copy=False)

    receipt_status = fields.Boolean(compute="_compute_receipt_status", default=False)
    amount_due_custom = fields.Monetary(compute="_compute_amount_due", string='Amount Due')
    currency_id = fields.Many2one("res.currency", string="Currency", readonly=True)
    ebiz_app_trans_internal_id = fields.Char("EBiz Application Transaction Id", copy=False)
    ebiz_application_transaction_ids = fields.One2many('ebiz.application.transaction', 'sale_order_id')
    customer_id = fields.Char("Customer Id", compute="_compute_customer_id")
    save_payment_link = fields.Char(string='Save Payment Link', copy=False)
    odoo_payment_link = fields.Boolean(string='Payment Link', copy=False, default=False)
    odoo_payment_link_doc = fields.Char(string='Payment Link Doc', copy=False)
    request_amount = fields.Float(string='Request Amount', copy=False)
    last_request_amount = fields.Float(string='Last Request Amount', copy=False)
    is_email_request = fields.Boolean(string='Email Pay sent', copy=False)
    ebiz_invoice_status = fields.Selection([
        ('default', ''),
        ('pending', 'Pending'),
        ('received', 'Received'),
        ('partially_received', 'Partially Received'),
        ('delete', 'Deleted'),
        ('applied', 'Applied'),
    ], string='Email Pay Status', default='default', readonly=True, copy=False, index=True)

    log_status_emv = fields.Char(string="Logs EMV", tracking=True, copy=False)
    emv_transaction_id = fields.Many2one('emv.device.transaction', string='Transaction ID', copy=False)
    transaction_type = fields.Selection([
        ('pre_auth', 'Pre-Authorize'),
        ('deposit', 'Deposit'),
    ], string='Transaction Type', index=True, copy=False)
    sale_enable_sur = fields.Boolean(string='Surcharge')

    @api.constrains('invoice_status')
    def check_invoice_status(self):
        for so in self:
            if so.partner_id.ebiz_profile_id and so.invoice_status == 'invoiced':
                ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=so.partner_id.ebiz_profile_id)
                received_payments = so._search_so_received_payments(ebiz)
                if not received_payments and so.save_payment_link and so.payment_internal_id:
                    so._invalidate_so_pay_link(ebiz)
                if so.partner_id.ebiz_profile_id.apply_sale_pay_inv and received_payments:
                    for item in received_payments:
                        so._apply_so_payment_item(ebiz, item)

    def _search_so_received_payments(self, ebiz):
        filters_list = [{'FieldName': 'InvoiceNumber', 'ComparisonOperator': 'eq', 'FieldValue': self.name}]
        today = datetime.now()
        return ebiz.client.service.SearchEbizWebFormReceivedPayments(**{
            'securityToken': ebiz._generate_security_json(),
            'fromPaymentRequestDateTime': str((today + timedelta(days=-365)).date()),
            'toPaymentRequestDateTime': str((today + timedelta(days=1)).date()),
            'start': 0,
            'limit': 10000,
            'filters': {'SearchFilter': filters_list},
        })

    def _invalidate_so_pay_link(self, ebiz):
        pay_link_deletion = ebiz.client.service.DeleteEbizWebFormPayment(**{
            'securityToken': ebiz._generate_security_json(),
            'paymentInternalId': self.payment_internal_id,
        })
        if self.save_payment_link:
            self.message_post(
                body=Markup(
                    'EBizCharge Payment Link invalidated: <a href="%s" target="_blank">%s</a>' % (
                        self.save_payment_link, self.save_payment_link)
                ),
                message_type="comment",
            )
        if pay_link_deletion:
            self.write({'save_payment_link': False, 'odoo_payment_link': False, 'request_amount': 0})

    def _apply_so_payment_item(self, ebiz, item):
        resp = ebiz.client.service.MarkEbizWebFormPaymentAsApplied(**{
            'securityToken': ebiz._generate_security_json(),
            'paymentInternalId': item['PaymentInternalId'],
        })
        if not (resp and resp['Status'] == 'Success'):
            return
        payment_acq = self.env['payment.provider'].search(
            [('company_id', '=', self.company_id.id if self.company_id else self.env.company.id),
             ('code', '=', 'ebizcharge')], limit=1)
        ebiz_method_tran = self.env['payment.method'].search(
            [('code', '=', 'ebizcharge')], limit=1)
        ebiz_method = self.env['account.payment.method.line'].search(
            [('journal_id', '=', payment_acq.journal_id.id),
             ('payment_method_id.code', '=', 'ebizcharge')], limit=1)
        transactions = ebiz.client.service.GetTransactionDetails(**{
            'securityToken': ebiz._generate_security_json(),
            'transactionRefNum': item['RefNum'],
        })
        payment = False
        transaction_type = 'pre_auth'
        if transactions['TransactionType'] not in ('Auth Only', 'Authonly'):
            payment = self.env['account.payment'].sudo().create({
                'journal_id': payment_acq.journal_id.id,
                'payment_method_id': ebiz_method.payment_method_id.id,
                'payment_method_line_id': ebiz_method.id,
                'partner_id': self.partner_id.id,
                'payment_reference': item['InvoiceNumber'] if item['InvoiceNumber'] else '',
                'amount': item['PaidAmount'],
                'partner_type': 'customer',
                'payment_type': 'inbound',
            })
            transaction_type = 'deposit'
        ebiz_transaction = self.env['payment.transaction'].sudo().create({
            'provider_id': payment_acq.sudo().id,
            'payment_method_id': ebiz_method_tran.id,
            'provider_reference': item['RefNum'],
            'reference': self.env['payment.transaction']._compute_reference(
                payment_acq.code, prefix=item['InvoiceNumber'] or self.name,
            ),
            'amount': item['PaidAmount'],
            'currency_id': payment_acq.company_id.currency_id.id,
            'partner_id': self.partner_id.id,
            'token_id': False,
            'operation': 'offline',
            'transaction_type': transaction_type,
            'sale_order_ids': [self.id],
            'invoice_ids': [fields.Command.set(self.invoice_ids.ids)],
            'payment_id': payment.id if payment else False,
        })
        self.write({'save_payment_link': False, 'odoo_payment_link': False, 'request_amount': 0})
        if payment:
            payment.payment_transaction_id = ebiz_transaction.id
        ebiz_transaction._set_authorized()
        self.write({'authorized_transaction_ids': [fields.Command.set([ebiz_transaction.id])]})
        if transactions['TransactionType'] not in ('Auth Only', 'Authonly'):
            ebiz_transaction._set_done()

    def action_confirm(self):
        ret = super().action_confirm()
        if self.partner_id.ebiz_profile_id:
            if self.partner_id.ebiz_profile_id.sales_auto_gpl and not self.save_payment_link and self.ebiz_amount_residual > 0.0:
                self.action_generate_pay_ebiz_link()
        return ret

    def js_update_enable_sur(self, **kwargs):
        if self.exists():
            self.write({'sale_enable_sur': kwargs.get('enable_sur')})
            if kwargs.get('res_id'):
                wizard_id = self.env['custom.register.payment'].browse(kwargs.get('res_id')).exists()
                wizard_id._onchange_enable_surcharge()

    def _prepare_sale_paylink_form(self, template, payment_method, lines):
        merchant_account_id = self.partner_id.ebiz_profile_id
        check_all_for_surcharge = [merchant_account_id, merchant_account_id.is_surcharge_enabled,
                                   merchant_account_id.merchant_toggle_sur_per_txn]
        sale_enable_sur = True
        surcharge_suffix = ';IsSurchargeEnabled=false' if all(check_all_for_surcharge) and not merchant_account_id.enable_sur_sales_auto_gpl else ''
        if merchant_account_id.gpl_pay_sale == 'pre_auth':
            processing_command = 'AuthOnly'
            pay_by_type = 'CC'
            self.transaction_type = 'pre_auth'
        else:
            processing_command = 'Sale'
            pay_by_type = payment_method
            self.transaction_type = 'deposit'
        if surcharge_suffix:
            processing_command += surcharge_suffix
            sale_enable_sur = False
        order_number = str(self.id) if str(self.name) == '/' else str(self.name)
        form = {
            'FormType': 'PayLinkOnly',
            'FromEmail': 'support@ebizcharge.com',
            'FromName': 'EBizCharge',
            'EmailSubject': template.template_subject,
            'EmailAddress': self.partner_id.email or ' ',
            'EmailTemplateID': template.template_id,
            'EmailTemplateName': template.name,
            'ShowSavedPaymentMethods': True,
            'CustFullName': self.partner_id.name,
            'TotalAmount': self.amount_total,
            'PayByType': pay_by_type,
            'AmountDue': self.ebiz_order_amount_residual,
            'ShippingAmount': 0,
            'ProcessingCommand': processing_command,
            'CustomerId': self.partner_id.ebiz_customer_id or self.partner_id.id,
            'ShowViewSalesOrderLink': True,
            'SendEmailToCustomer': False,
            'TaxAmount': self.amount_tax,
            'SoftwareId': 'ODOOPayLinkOnly',
            'SalesOrderInternalId': self.ebiz_internal_id,
            'Description': 'SalesOrder',
            'DocumentTypeId': 'SalesOrder',
            'PoNum': self.client_order_ref or self.name,
            'OrderId': order_number,
            'InvoiceNumber': " ".join(part for part in [order_number, self.client_order_ref] if part)
                if merchant_account_id.payment_memo_setting == 'dn_pon_pm' else order_number,
            'Date': self.date_order,
            'BillingAddress': _prepare_billing_address(self),
            'LineItems': _transaction_lines(lines),
        }
        if self.partner_id.ebiz_customer_id:
            form['CustomerId'] = self.partner_id.ebiz_customer_id
        return form, sale_enable_sur

    def action_generate_pay_ebiz_link(self):
        template = self.env['email.templates'].search([('template_type_id', '=', 'SalesOrderWebFormEmail'),
            ('instance_id', '=', self.partner_id.ebiz_profile_id.id)], limit=1)
        if template:
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=self.partner_id.ebiz_profile_id)
            lines = self.order_line
            get_merchant_data = False
            get_allow_credit_card_pay = False
            if self.partner_id.ebiz_profile_id:
                get_merchant_data = self.partner_id.ebiz_profile_id.merchant_data
                get_allow_credit_card_pay = self.partner_id.ebiz_profile_id.allow_credit_card_pay
            payment_method = 'CC'
            if get_merchant_data and get_allow_credit_card_pay:
                payment_method = 'CC,ACH'
            elif get_merchant_data:
                payment_method = 'ACH'
            elif get_allow_credit_card_pay:
                payment_method = 'CC'
            ePaymentForm, sale_enable_sur = self._prepare_sale_paylink_form(template, payment_method, lines)
            form_url = ebiz.client.service.GetEbizWebFormURL(**{
                'securityToken': ebiz._generate_security_json(),
                'ePaymentForm': ePaymentForm
            })
            self.write({'sale_enable_sur': sale_enable_sur, 'save_payment_link': form_url, 'is_email_request': False, 'payment_internal_id': form_url.split('=')[1]})
            if self.save_payment_link:
                self.message_post(
                    body=Markup(
                        'New EBizCharge Payment Link has been generated: <a href="%s" target="_blank">%s</a>' % (form_url, form_url)
                    ),
                    message_type="comment",
                )
        else:
            self.message_post(body="Can't auto generate link for Sales Order, because Email Template for 'SalesOrderWebFormEmail' not found, Please set one from Admin Portal.")

    def _log_pay_link(self):
        for line in self:
            instance = self.partner_id.ebiz_profile_id
            if self.save_payment_link and self.payment_internal_id and instance:
                ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
                ebiz.client.service.DeleteEbizWebFormPayment(**{
                    'securityToken': ebiz._generate_security_json(),
                    'paymentInternalId': self.payment_internal_id,
                })
            if self.save_payment_link:
                self.message_post(
                    body=Markup(
                        'EBizCharge Payment Link invalidated: <a href="%s" target="_blank">%s</a>' % (
                            self.save_payment_link, self.save_payment_link)
                    ),
                    message_type="comment",
                )
                self.save_payment_link = False
            if line.odoo_payment_link_doc:
                line.message_post(
                    body=Markup(
                        'New Payment Link has been generated: <a href="%s" target="_blank">%s</a>' % (
                            line.odoo_payment_link_doc, line.odoo_payment_link_doc)
                    ),
                    message_type="comment",
                )

    def _compute_receipt_status(self):
        receipts = self.env['account.move.receipts']
        for order in self:
            order.receipt_status = bool(receipts.search([('invoice_id', '=', order.id)]))

    def _compute_ebiz_auto_sync(self):
        for rec in self:
            rec.ebiz_auto_sync = False

    def _compute_order_pre_auth(self):
        for sal in self:
            transaction = self.env['payment.transaction'].sudo().search(
                [('reference', '=', sal.name), ('state', 'in', ('pending', 'authorized', 'done'))])
            for uniq_trans in transaction:
                uniq_trans.write({'sale_order_ids': [fields.Command.set([sal.id])]})
            transactions = self.env['payment.transaction'].sudo().search(
                [('state', 'in', ('pending', 'authorized', 'done')), '|',
                 ('sale_order_ids', 'in', sal.ids), ('invoice_ids', 'in', sal.invoice_ids.ids)])
            sum_amount_ebiz = sum(
                t.captured_amount if t.captured_amount > 0 else t.amount for t in transactions)
            amt_calc = sal.amount_total - sum_amount_ebiz
            sal.ebiz_order_amount_residual = amt_calc if amt_calc > 0.0 else 0

    def generate_payment_link(self):
        try:
            if len(self) == 0:
                raise UserError('Please select a record first!')
            if len(self.partner_id.ebiz_profile_id) > 1:
                raise UserError('Filter the Orders for a specific unique merchant account. Selection of Orders for more than one merchant account is not allowed.')

            profile = False
            payment_lines = []
            odoo_pay_link = any(order.odoo_payment_link for order in self)
            ebiz_pay_link = any(order.save_payment_link for order in self)

            if odoo_pay_link:
                text = "This document has a pending payment link. Proceeding may increase the risk of double payments. Do you want to continue?"
                wizard = self.env['wizard.receive.email.payment.link'].create({
                    "sale_ids": [fields.Command.set(self.ids)],
                    "text": text,
                })
                action = self.env.ref('payment_ebizcharge_crm.wizard_received_email_pay_payment_link').read()[0]
                action['res_id'] = wizard.id
                return action
            elif ebiz_pay_link:
                text = "This document has an existing payment link. Proceeding will invalidate the existing link. Do you want to continue?"
                wizard = self.env['wizard.receive.email.payment.link'].create({
                    "sale_ids": [fields.Command.set(self.ids)],
                    "text": text,
                })
                action = self.env.ref('payment_ebizcharge_crm.wizard_received_email_pay_payment_link').read()[0]
                action['res_id'] = wizard.id
                return action
            else:
                for inv in self:
                    if not inv.save_payment_link:
                        payment_lines.append(fields.Command.create({
                            "order_id": inv.id,
                            "partner_id": inv.partner_id.id,
                            "transaction_type": inv.partner_id.ebiz_profile_id.gpl_pay_sale,
                            "amount_total_signed": inv.amount_total,
                            "request_amount": inv.ebiz_order_amount_residual,
                            "so_payment_link": inv.odoo_payment_link,
                            "currency_id": self.env.user.currency_id.id,
                            "email_id": inv.partner_id.email,
                            "ebiz_profile_id": inv.partner_id.ebiz_profile_id.id,
                        }))
                        profile = inv.partner_id.ebiz_profile_id.id
                wiz = self.env['wizard.generate.so.link.payment'].with_context(profile=profile).create({
                    'payment_lines': payment_lines,
                    'sale_link': True,
                    'ebiz_profile_id': profile,
                })
                action = self.env.ref('payment_ebizcharge_crm.wizard_generate_so_link_form_views_action').read()[0]
                action['res_id'] = wiz.id
                action['context'] = self.env.context
                return action
        except Exception as e:
            raise ValidationError(e)

    def _compute_pre_auth(self):
        for sal in self:
            transaction = self.env['payment.transaction'].sudo().search(
                [('reference', '=', sal.name), ('state', 'in', ('pending', 'authorized', 'done'))])
            for uniq_trans in transaction:
                uniq_trans.write({'sale_order_ids': [fields.Command.set([sal.id])]})
            inv_list = sal.invoice_ids.mapped('payment_state')
            transactions = self.env['payment.transaction'].sudo().search(
                [('state', 'in', ('pending', 'authorized', 'done')), '|',
                 ('sale_order_ids', 'in', sal.ids), ('invoice_ids', 'in', sal.invoice_ids.ids)])
            sum_amount_ebiz = sum(
                t.captured_amount if t.captured_amount > 0 else t.amount for t in transactions)
            if sum_amount_ebiz >= sal.amount_total:
                sal.ebiz_amount_residual += sal.request_amount
            else:
                amt_calc = (sal.amount_total - sum_amount_ebiz) - sal.request_amount
                sal.ebiz_amount_residual = amt_calc if amt_calc > 0.0 else 0
            check = bool(sal.invoice_ids) and all(x in ['paid', 'in_payment'] for x in inv_list)
            sal.is_pre_auth = bool(transaction or check)

    @api.depends('partner_id')
    def _compute_customer_id(self):
        for sal in self:
            sal.customer_id = sal.partner_id.id

    @api.depends('invoice_ids.amount_residual')
    def _compute_amount_due(self):
        for entry in self:
            entry.amount_due_custom = entry.invoice_ids[0].amount_residual if entry.invoice_ids else entry.amount_total

    @api.depends('ebiz_internal_id')
    def _compute_sync_status(self):
        for order in self:
            order.sync_status = "Synchronized" if order.ebiz_internal_id else "Pending"

    @api.depends('invoice_ids.payment_state')
    def _compute_invoice_payment_status(self):
        for rec in self:
            rec.is_invoice_paid = bool(rec.invoice_ids) and rec.invoice_ids[0].payment_state == "paid"

    @api.depends('transaction_ids.provider_reference')
    def _compute_trans_ref(self):
        for rec in self:
            rec.ebiz_transaction_ref = rec.transaction_ids[0].provider_reference if rec.transaction_ids else ""

    @api.depends('transaction_ids')
    def _compute_done_transaction_ids(self):
        for trans in self:
            trans.done_transaction_ids = trans.transaction_ids.filtered(lambda t: t.state == 'done')

    @api.model_create_multi
    def create(self, values):
        record = super().create(values)
        for rec in record:
            if rec.partner_id.ebiz_profile_id and rec.partner_id.ebiz_profile_id.ebiz_auto_sync_sale_order:
                rec.sync_to_ebiz()
        return record

    def ebiz_create_payment_line(self, amount):
        acquirer = self.env['payment.provider'].search(
            [('company_id', '=', self.company_id.id), ('code', '=', 'ebizcharge')])
        journal_id = acquirer.journal_id
        ebiz_method = self.env['account.payment.method.line'].search(
            [('journal_id', '=', journal_id.id), ('payment_method_id.code', '=', 'ebizcharge')], limit=1)
        payment = self.env['account.payment'].sudo().with_context(
            active_ids=self.ids, active_model='sale.order', active_id=self.id).create({
            'journal_id': journal_id.id,
            'payment_method_id': ebiz_method.payment_method_id.id if ebiz_method else False,
            'payment_method_line_id': ebiz_method.id if ebiz_method else False,
            'token_type': None,
            'amount': amount,
            'partner_id': self.partner_id.id,
            'ref': self.name or None,
            'payment_type': 'inbound'
        })
        payment.with_context({'do_not_run_transaction': True}).action_post()

    def delete_ebiz_so_link(self):
        try:
            instance = self.partner_id.ebiz_profile_id or None
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
            received_payments = ebiz.client.service.DeleteEbizWebFormPayment(**{
                'securityToken': ebiz._generate_security_json(),
                'paymentInternalId': self.payment_internal_id,
            })
            if received_payments:
                self.write({'save_payment_link': False, 'odoo_payment_link': False, 'request_amount': 0})
        except Exception as e:
            raise ValidationError(e)

    def sync_to_ebiz_ind(self):
        self.sync_to_ebiz()
        return message_wizard('Sales order uploaded successfully!')

    def sync_to_ebiz(self, time_sample=None):
        self.ensure_one()
        instance = self.partner_id.ebiz_profile_id or self.env['ebizcharge.instance.config'].search(
            [('is_valid_credential', '=', True), ('is_default', '=', True)], limit=1)
        ebiz = self.get_ebiz_object(instance)
        update_params = {}
        if not self.partner_id.ebiz_internal_id:
            self.partner_id.sync_to_ebiz()
        if self.ebiz_internal_id:
            resp = ebiz.update_sale_order(self)
        else:
            resp = ebiz.sync_sale_order(self)
            if resp['ErrorCode'] == 2:
                resp_search = self.ebiz_search_sale_order()
                update_params.update({'ebiz_internal_id': resp_search['SalesOrderInternalId']})
            if resp and not resp['ErrorCode'] == 2:
                update_params.update({'ebiz_internal_id': resp['SalesOrderInternalId']})
        self.create_odoo_logs(resp)
        update_params.update({
            "last_sync_date": fields.Datetime.now(),
            "sync_response": 'Success' if resp['ErrorCode'] in [0, 2] else resp['Error']})
        self.write(update_params)
        self.ebiz_application_transaction_ids.ebiz_add_application_transaction()
        return resp

    def create_odoo_logs(self, resp):
        self.env['logs.of.orders'].create({
            'order_no': self.id,
            'customer_id': self.partner_id.id,
            'currency_id': self.env.user.currency_id.id,
            'sync_status': 'Success' if resp['ErrorCode'] in [0, 2] else resp['Error'],
            'last_sync_date': datetime.now(),
            'user_id': self.env.user.id,
            'amount_total': self.amount_total,
            'amount_due': self.amount_due_custom,
            'order_date': self.date_order,
        })

    def ebiz_search_sale_order(self):
        instance = self.partner_id.ebiz_profile_id or None
        ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
        resp = ebiz.client.service.SearchSalesOrders(**{
            'securityToken': ebiz._generate_security_json(),
            'customerId': self.partner_id.id,
            'salesOrderNumber': self.name,
            'start': 0,
            'limit': 0,
            'includeItems': False
        })
        return resp[0] if resp else resp

    def run_ebiz_transaction(self, payment_token_id, command, token_ebiz=None):
        self.ensure_one()
        if not self.partner_id.ebiz_internal_id and payment_token_id and payment_token_id.partner_id.id == self.partner_id.id:
            self.partner_id.sync_to_ebiz()
        instance = (
            (payment_token_id and payment_token_id.partner_id.ebiz_profile_id)
            or self.partner_id.ebiz_profile_id
            or self.env.user.partner_id.ebiz_profile_id
            or self.env['ebizcharge.instance.config'].search(
                [('is_valid_credential', '=', True), ('is_default', '=', True)], limit=1)
        )
        ebiz = self.get_ebiz_object(instance)
        if token_ebiz:
            resp = ebiz.run_transaction(self, payment_token_id, command, token_ebiz=token_ebiz)
        elif self.env.user._is_public():
            resp = ebiz.run_transaction(self, payment_token_id, command)
        else:
            if payment_token_id and not payment_token_id.ebizcharge_profile:
                payment_token_id.action_sync_token_to_ebiz()
            if not self.partner_id.ebizcharge_customer_token:
                self.partner_id.sync_to_ebiz()
            resp = ebiz.run_customer_transaction(self, payment_token_id, command, current_user=self.env.user.partner_id)
        if self.invoice_ids:
            self.invoice_ids.transaction_ids = [fields.Command.set(self.transaction_ids.ids)]
        return resp

    def get_ebiz_object(self, instance):
        web = self.env['ir.module.module'].sudo().search(
            [('name', '=', 'website_sale'), ('state', 'in', ['installed', 'to upgrade', 'to remove'])])
        ebiz_obj = self.env['ebiz.charge.api']
        if web:
            ebiz = ebiz_obj.get_ebiz_charge_obj(self.website_id.id, instance=instance)
        else:
            ebiz = ebiz_obj.get_ebiz_charge_obj(instance=instance)
        return ebiz

    def run_ebiz_refund_transaction(self):
        self.ensure_one()
        if not self.partner_id.payment_token_ids:
            raise ValidationError("Please enter payment methode profile on the customer to run transaction.")
        vals = {
            'provider_id': self.env['payment.provider'].search(
                [('company_id', '=', self.company_id.id), ('code', '=', 'ebizcharge')]).id,
            'payment_token_id': self.partner_id.payment_token_ids.id,
        }
        self._create_payment_transaction(vals)
        return True

    def sync_multi_sale_orders(self):
        resp_lines = []
        success = failed = 0
        total = len(self)
        for so in self:
            resp_line = {
                'customer_name': so.partner_id.name,
                'customer_id': so.partner_id.id,
                'order_number': so.name,
            }
            try:
                resp = so.sync_to_ebiz()
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
            'name': 'sales orders',
            'order_lines_ids': resp_lines,
            'success_count': success,
            'failed_count': failed,
            'total': total,
        })
        action = self.env.ref('payment_ebizcharge_crm.wizard_multi_sync_message_action').read()[0]
        action['context'] = self.env.context
        action['res_id'] = wizard.id
        return action

    def write(self, values):
        ret = super().write(values)
        if 'ebiz_internal_id' in values:
            return ret
        for order in self:
            if order._ebzi_check_update_sync(values) and order.ebiz_internal_id:
                order.sync_to_ebiz()
        return ret

    def _ebzi_check_update_sync(self, values):
        update_fields = {"partner_id", "name", "date_order", "amount_total",
                         "currency_id", "amount_tax", "expected_date", "user_id", "order_line", "state"}
        return bool(update_fields.intersection(values))

    def pre_authorize(self):
        if len(self.ids) > 1:
            raise UserError('Unable to process more than 1 sales order.')
        if not self.partner_id.ebiz_profile_id:
            default_instance = self.env['ebizcharge.instance.config'].search(
                [('is_valid_credential', '=', True), ('is_default', '=', True)], limit=1)
            if default_instance:
                self.partner_id.write({'ebiz_profile_id': default_instance.id})
            else:
                raise UserError('No EBizCharge profile selected in customer..')
        if self.emv_transaction_id:
            self.emv_transaction_id.action_check(trans=self.emv_transaction_id.id)
        if self.ebiz_amount_residual == 0 and self.request_amount == 0:
            raise UserError('This sale order is already processed.')

        instance = self.partner_id.ebiz_profile_id
        allow_credit_card_pay = instance.allow_credit_card_pay
        merchant_data = instance.merchant_data

        if instance.is_emv_enabled:
            instance.action_get_devices()
        return {
            'name': 'Register Payment',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'custom.register.payment',
            'view_id': False,
            'type': 'ir.actions.act_window',
            'target': 'new',
            'context': {
                'default_amount': self.ebiz_amount_residual,
                'default_date': datetime.now().date(),
                'default_ebiz_receipt_emails': self.partner_id.email,
                'default_order_id': self.id,
                'default_memo': self.name,
                'partner_id': self.partner_id.id,
                'sub_partner_id': self.partner_id.id,
                'default_card_functionality_hide': allow_credit_card_pay,
                'default_ach_functionality_hide': merchant_data,
                'default_is_ebiz_profile': True,
                'default_ebiz_profile_id': instance.id,
                'default_required_security_code': instance.verify_card_before_saving,
                'default_is_pay_link': bool(self.save_payment_link),
                'hide_payment_journal_id': True,
            }
        }

    def _has_to_be_paid(self):
        self.ensure_one()
        transaction = self.get_portal_last_transaction()
        return (
            self.state in ['draft', 'sent', 'sale']
            and not self.is_expired
            and self.require_payment
            and transaction.state not in ['done', 'authorized']
            and self.amount_total > 0
        )


class SaleOrderLineInh(models.Model):
    _inherit = 'sale.order.line'

    @api.depends('state', 'product_uom_qty', 'qty_delivered', 'qty_to_invoice', 'qty_invoiced')
    def _compute_invoice_status(self):
        super()._compute_invoice_status()
        precision = self.env['decimal.precision'].precision_get('Product Unit')
        for line in self:
            # If qty_invoiced >= qty_ordered the line is fully invoiced, regardless of
            # qty_to_invoice being negative (delivery-policy product invoiced before delivery).
            if line.invoice_status == 'to invoice' and float_compare(
                line.qty_invoiced, line.product_uom_qty, precision_digits=precision
            ) >= 0:
                line.invoice_status = 'invoiced'


class EBizApplicationTransactions(models.Model):
    _name = "ebiz.application.transaction"
    _description = "EBiz Application Transaction"

    ebiz_internal_id = fields.Char('Application Transaction Internal Id')
    partner_id = fields.Many2one('res.partner')
    sale_order_id = fields.Many2one('sale.order')
    transaction_id = fields.Many2one('payment.transaction')
    transaction_type = fields.Char('Transaction Command')
    is_applied = fields.Boolean('Is Applied', default=False)

    def ebiz_add_application_transaction(self):
        for trans in self:
            trans.ebiz_single_application_transaction()

    def mark_application_transaction_as_applied(self):
        instance = self.partner_id.ebiz_profile_id or None
        ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
        for trans in self:
            if not trans.is_applied:
                resp = ebiz.client.service.MarkApplicationTransactionAsApplied(**{
                    'securityToken': ebiz._generate_security_json(),
                    'applicationTransactionInternalId': trans.ebiz_internal_id
                })
                if resp['StatusCode'] == 1:
                    trans.is_applied = True

    def ebiz_single_application_transaction(self):
        if self.sale_order_id.ebiz_internal_id and self.transaction_id.provider_reference and not self.ebiz_internal_id:
            instance = self.partner_id.ebiz_profile_id or None
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
            params = {
                'securityToken': ebiz._generate_security_json(),
                'applicationTransactionRequest': {
                    'CustomerInternalId': self.partner_id.ebiz_internal_id,
                    'TransactionId': self.transaction_id.provider_reference,
                    'TransactionTypeId': self.transaction_type,
                    'LinkedToTypeId': 'SalesOrder',
                    'LinkedToExternalUniqueId': self.sale_order_id.id,
                    'LinkedToInternalId': self.sale_order_id.ebiz_internal_id,
                    'SoftwareId': "Odoo CRM",
                    'TransactionDate': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'TransactionNotes': "Order No: {}".format(self.sale_order_id.name)
                }
            }
            resp = ebiz.client.service.AddApplicationTransaction(**params)
            if resp['StatusCode'] == 1:
                self.ebiz_internal_id = resp['ApplicationTransactionInternalId']
                self.mark_application_transaction_as_applied()
            return resp
        else:
            _logger.info('cannot add application transaction on order No: {}'.format(self.sale_order_id.name))
