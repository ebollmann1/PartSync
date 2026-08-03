# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import logging
from datetime import datetime, timedelta
from .ebiz_charge import message_wizard

_logger = logging.getLogger(__name__)


class PaymentRequestBulkPayment(models.Model):
    _name = 'payment.request.bulk.email'
    _description = "Payment Request Bulk Email"

    def get_default_company(self):
        return self.env['ebizcharge.instance.config'].search(
            [('is_active', '=', True), '|', ('company_ids', '=', False),
             ('company_ids', 'in', self.env.context.get('allowed_company_ids'))]).company_ids.ids

    company_ids = fields.Many2many('res.company', compute='compute_company')
    start_date = fields.Date(string='From Date')
    end_date = fields.Date(string='To Date')
    name = fields.Char(string='Email Pay for Invoices', default='Email Pay for Invoices')
    partner_id = fields.Many2one('res.partner', string='Select Customer',
                                      domain="[('ebiz_internal_id', '!=', False), ('ebiz_profile_id', '=', ebiz_profile_id)]")
    transaction_history_line = fields.One2many('sync.request.payments.bulk', 'sync_transaction_id', copy=True)
    transaction_history_line_pending = fields.One2many('sync.request.payments.bulk.pending', 'sync_transaction_id_pending')
    transaction_history_line_received = fields.One2many('sync.request.payments.bulk.received', 'sync_transaction_id_received')
    add_filter = fields.Boolean(string='Filters')
    ebiz_profile_id = fields.Many2one('ebizcharge.instance.config', string='EBizCharge Profile')
    is_reopened = fields.Boolean(default=False)
    enable_surcharge_for_all = fields.Selection([('none', 'None'), ('enable', 'Enable'), ('disable', 'Disable')], default='enable')

    merchant_toggle_sur_per_txn = fields.Boolean(related='ebiz_profile_id.merchant_toggle_sur_per_txn')
    is_surcharge_enabled = fields.Boolean(string="Surcharge Enabled", related='ebiz_profile_id.is_surcharge_enabled')
    is_surcharge_toggle_visible = fields.Boolean(default=False)

    @api.depends('ebiz_profile_id')
    def compute_company(self):
        self.company_ids = self.env.context.get('allowed_company_ids')

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = 'Email Pay for Invoices'

    def set_merchant_initial_values(self):
        profile_obj = self.env['ebizcharge.instance.config']
        profile = int(profile_obj.get_upload_instance(active_model='payment.request.bulk.email', active_id=self))
        if profile:
            self.ebiz_profile_id = profile
            self.start_date = self.ebiz_profile_id._default_get_start()
            self.end_date = self.ebiz_profile_id._default_get_end_date()

    def _prepare_new_invoices_values(self, invoice, partner):
        values = {
            'name': invoice['name'],
            'customer_id': partner.id,
            'invoice_id': invoice.id,
            'invoice_date': invoice.date,
            'sales_person': self.env.user.id,
            'amount': invoice.amount_total,
            "currency_id": invoice.currency_id.id,
            'amount_due': invoice.amount_residual_signed,
            'tax': invoice.amount_untaxed_signed,
            'invoice_due_date': invoice.invoice_date_due,
        }
        if self.enable_surcharge_for_all == 'disable':
            values['inv_enable_sur'] = False
            invoice.inv_enable_sur = False
        else:
            values['inv_enable_sur'] = True
            invoice.inv_enable_sur = True
        return values

    def _prepare_pending_invoices_values(self, invoice, partner, date_check):
        return {
            'name': invoice['name'],
            'customer_id': partner.id,
            'invoice_id': invoice.id,
            'invoice_date': invoice.date,
            'email_id': invoice.email_for_pending if invoice.email_for_pending else invoice.partner_id.email,
            'sales_person': self.env.user.id,
            'amount': invoice.amount_total,
            "currency_id": invoice.currency_id.id,
            'amount_due': invoice.amount_residual_signed,
            'tax': invoice.amount_untaxed_signed,
            'date_and_time_Sent': invoice.date_time_sent_for_email or None,
            'over_due_status': date_check if date_check else None,
            'invoice_due_date': invoice.invoice_date_due,
            'sync_transaction_id_pending': self.id,
            'ebiz_status': 'Pending' if invoice.ebiz_invoice_status == 'pending' else invoice.ebiz_invoice_status,
            'email_requested_amount': invoice.email_requested_amount,
            'no_of_times_sent': invoice.no_of_times_sent,
        }

    def _prepare_received_invoices_values(self, invoice, partner, portal_invoice):
        return {
            'name': invoice['name'],
            'customer_id': partner.id,
            'invoice_id': invoice.id,
            'invoice_date': invoice.date,
            "currency_id": invoice.currency_id.id,
            'sales_person': self.env.user.id,
            'amount': float(invoice.amount_total),
            'amount_due': float(invoice.amount_residual_signed),
            'paid_amount': float(portal_invoice['PaidAmount']),
            'email_id': portal_invoice['CustomerEmailAddress'],
            'ref_num': portal_invoice['RefNum'],
            'payment_request_date_time': datetime.strptime(portal_invoice['PaymentRequestDateTime'],
                                                           '%Y-%m-%dT%H:%M:%S'),
            'payment_method': f"{portal_invoice['PaymentMethod']} ending in {portal_invoice['Last4']}",
            'sync_transaction_id_received': self.id,
        }

    def regenerate_line_ids(self, enable_surcharge_for_all=None):
        if not self.ebiz_profile_id:
            self.set_merchant_initial_values()
        self.is_surcharge_toggle_visible = self.merchant_toggle_sur_per_txn and self.is_surcharge_enabled
        self._create_transaction_history_line()
        self._create_pending_and_received_history()

    def _create_transaction_history_line(self):
        list_of_invoices = [fields.Command.clear()]
        if self.ebiz_profile_id:
            invoices = self.default_invoice()
            list_of_invoices += [
                fields.Command.create(self._prepare_new_invoices_values(invoice, invoice.partner_id))
                for invoice in invoices
            ]
        self.transaction_history_line = list_of_invoices

    def _create_pending_and_received_history(self):
        list_of_received = []
        list_of_pending = []
        self.transaction_history_line_pending.unlink()
        self.transaction_history_line_received.unlink()
        if self.ebiz_profile_id:
            pending_invoices = self.default_pending_invoice()
            payments = self.default_received_invoices()
            list_of_pending = self.get_pending_payment_list(pending_invoices, payments)
            list_of_received = self.get_received_payment_list(payments) if payments else []

        self.env['sync.request.payments.bulk.received'].create(list_of_received)
        self.env['sync.request.payments.bulk.pending'].create(list_of_pending)

    def get_received_payment_list(self, payments):
        list_of_received = []
        for portal_invoice in payments:
            invoice = self.env['account.move'].search(
                [('payment_internal_id', '=', portal_invoice['PaymentInternalId'])])
            if invoice:
                partner = invoice.partner_id
                list_of_received.append(self._prepare_received_invoices_values(invoice, partner, portal_invoice))
        return list_of_received

    def get_pending_payment_list(self, pending_invoices, payments):
        list_of_pending = []
        for invoice in pending_invoices:
            check = True
            partner = invoice.partner_id
            if payments: #Getting API response in payments, sometimes it gets None, that's why condition is applied.
                for invoice_check in payments:
                    if invoice.payment_internal_id == invoice_check['PaymentInternalId']:
                        check = False

            if check:
                date_check = False
                if invoice.date_time_sent_for_email:
                    date_check = 'due in 3 days' if (datetime.now() - invoice.date_time_sent_for_email).days <= 3 else '3 days overdue'
                list_of_pending.append(self._prepare_pending_invoices_values(invoice, partner, date_check))
        return list_of_pending

    def action_open_email_pay_invoices(self):
        profile_obj = self.env['ebizcharge.instance.config']
        profile = int(profile_obj.get_upload_instance(active_model='payment.request.bulk.email', active_id=self))
        record = self
        if profile:
            ebiz_profile_id = self.env['ebizcharge.instance.config'].browse(int(profile))
            record = self.create({'ebiz_profile_id': profile,
                         'start_date': ebiz_profile_id._default_get_start(),
                         'end_date': ebiz_profile_id._default_get_end_date()})

            record.regenerate_line_ids()
        return {
            "name": _("Email Pay for Invoices"),
            "type": "ir.actions.act_window",
            "res_model": "payment.request.bulk.email",
            "res_id": record.id,
            'view_id': self.env.ref('payment_ebizcharge_crm.form_view_payment_request_bulk_email', False).id,
            "view_mode": "form",
            "target": "inline",
        }

    def default_invoice(self):
        filters = [
            ('payment_state', '!=', 'paid'),
            ('state', '=', 'posted'),
            ('odoo_payment_link', '=', False),
            ('ebiz_invoice_status', '!=', 'pending'),
            ('save_payment_link', '=', False),
            ('amount_residual', '>', 0),
            ('move_type', 'not in', ['out_refund', 'in_invoice'])
        ]
        if self.end_date:
            filters.append(('date', '<=', self.end_date))
        if self.start_date:
            filters.append(('date', '>=', self.start_date))
        if self.partner_id:
            filters.append(('partner_id', '=', self.partner_id.id))
        if self.ebiz_profile_id:
            filters.append(('partner_id.ebiz_profile_id', '=', self.ebiz_profile_id.id))

        return self.env['account.move'].search(filters)

    def default_pending_invoice(self):
        filters = [
            ('payment_state', '!=', 'paid'),
            ('state', '=', 'posted'),
            ('ebiz_invoice_status', '=', 'pending'),
            ('ebiz_invoice_status', '!=', 'delete'),
            ('amount_residual', '>', 0),
            ('move_type', '!=', 'out_refund')
        ]
        if self.end_date:
            filters.append(('date', '<=', self.end_date))
        if self.start_date:
            filters.append(('date', '>=', self.start_date))
        if self.partner_id:
            filters.append(('partner_id', '=', self.partner_id.id))
        if self.ebiz_profile_id:
            filters.append(('partner_id.ebiz_profile_id', '=', self.ebiz_profile_id.id))

        return self.env['account.move'].search(filters)

    def default_received_invoices(self):
        ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=self.ebiz_profile_id)
        dicti = {
            'securityToken': ebiz._generate_security_json(),
            'filters': {'SearchFilter': []},
            'fromPaymentRequestDateTime': self.start_date,
            'toPaymentRequestDateTime': self.end_date,
            'start': 0,
            'limit': 100000,
        }
        if self.partner_id:
            dicti['customerId'] = self.partner_id.id
        return ebiz.client.service.SearchEbizWebFormReceivedPayments(**dicti)


class ListSyncBulkInvoices(models.Model):
    _name = 'sync.request.payments.bulk'
    _order = 'date_time asc'
    _description = "Sync Request Payment Bulk"

    sync_date = fields.Datetime('Execution Date/Time', required=True, default=fields.Datetime.now)
    sync_transaction_id = fields.Many2one('payment.request.bulk.email', string='Partner Reference', required=True,
                                          ondelete='cascade', index=True, copy=False)
    merchant_toggle_sur_per_txn = fields.Boolean(related='sync_transaction_id.merchant_toggle_sur_per_txn')
    is_surcharge_enabled = fields.Boolean(string="Surcharge Enabled", related='sync_transaction_id.is_surcharge_enabled')
    is_surcharge_toggle_visible = fields.Boolean(related='sync_transaction_id.is_surcharge_toggle_visible')
    inv_enable_sur = fields.Boolean(string='Surcharge')
    enable_surcharge_for_all = fields.Boolean(
        compute='_compute_enable_surcharge_for_all',
        inverse='_inverse_enable_surcharge_for_all',
    )

    @api.depends('inv_enable_sur')
    def _compute_enable_surcharge_for_all(self):
        for rec in self:
            rec.enable_surcharge_for_all = rec.inv_enable_sur

    def _inverse_enable_surcharge_for_all(self):
        for rec in self:
            rec.inv_enable_sur = rec.enable_surcharge_for_all

    name = fields.Char(string='Number')
    customer_id = fields.Many2one('res.partner', string='Customer')
    invoice_id = fields.Many2one('account.move', string='Invoice')
    account_holder = fields.Char(string='Account Holder')
    date_time = fields.Datetime(string='Date Time')
    currency_id = fields.Many2one('res.currency', string='Company Currency')
    amount = fields.Float(string='Invoice Total')
    amount_due = fields.Float(string='Amount Due')
    tax = fields.Float(string='Tax Excluded')
    card_no = fields.Char(string='Card Number')
    status = fields.Char(string='Status')
    email_id = fields.Char(string='Email', related='customer_id.email')
    invoice_date = fields.Date(string='Invoice Date')
    invoice_due_date = fields.Date(string='Due Date')
    sales_person = fields.Many2one('res.users', string='Sales Person')
    payment_method = fields.Char('Payment Method')
    default_card_id = fields.Integer(string='Default Credit Card ID')

    def _prepare_payment_wizard_lines(self, invoice_id):
        return {
            "name": invoice_id.name,
            "customer_name": invoice_id.partner_id.id,
            "amount_due": invoice_id.amount_residual_signed,
            "invoice_id": invoice_id.id,
            "currency_id": self.env.user.currency_id.id,
            "email_id": invoice_id.partner_id.email,
            "ebiz_profile_id": invoice_id.partner_id.ebiz_profile_id.id,
            "enable_surcharge": self.inv_enable_sur,
            "sync_request_id": self.id,
        }

    def send_email_pay_wizard(self):
        """
            Email receipt to customer, if email receipts templates not there in odoo, it will fetch.
            return: wizard to select the receipt template
        """
        try:
            for record in self:
                record.invoice_id.inv_enable_sur = record.inv_enable_sur
            payment_lines = [
                fields.Command.create(record._prepare_payment_wizard_lines(record.invoice_id))
                for record in self
            ]
            ebiz_profile_id = self.sync_transaction_id.ebiz_profile_id
            wiz = self.env['ebiz.request.payment.bulk'].with_context(profile=ebiz_profile_id.id, record_ids=self.ids).create({
                'payment_lines': payment_lines,
                'ebiz_profile_id': ebiz_profile_id.id,
            })
            action = self.env.ref('payment_ebizcharge_crm.action_ebiz_request_payments_bulk').read()[0]
            action['res_id'] = wiz.id
            action['context'] = self.env.context
            return action
        except Exception as e:
            raise UserError(e)



class ListPendingBulkInvoices(models.Model):
    _name = 'sync.request.payments.bulk.pending'
    _order = 'date_time asc'
    _description = "Sync Request Payments Bulk Pending"

    sync_date = fields.Datetime('Execution Date/Time', required=True, default=fields.Datetime.now)
    sync_transaction_id_pending = fields.Many2one('payment.request.bulk.email', string='Partner Reference',
                                                  required=True, ondelete='cascade', index=True, copy=False)
    name = fields.Char(string='Number')
    customer_id = fields.Many2one('res.partner', string='Customer')
    invoice_id = fields.Many2one('account.move', string='Invoice')
    currency_id = fields.Many2one('res.currency', string='Company Currency')
    account_holder = fields.Char(string='Account Holder')
    date_time = fields.Datetime(string='Date Time')
    amount = fields.Float(string='Invoice Total')
    amount_due = fields.Float(string='Amount Due')
    tax = fields.Float(string='Tax Excluded')
    card_no = fields.Char(string='Card Number')
    status = fields.Char(string='Status')
    email_id = fields.Char(string='Email')
    invoice_date = fields.Date(string='Invoice Date')
    invoice_due_date = fields.Date(string='Due Date')
    sales_person = fields.Many2one('res.users', string='Sales Person')
    payment_method = fields.Char('Payment Method')
    ebiz_status = fields.Char('Ebiz Status')
    over_due_status = fields.Char('Overdue Status')
    date_and_time_Sent = fields.Datetime('Org. Date & Time Sent')
    email_requested_amount = fields.Float('Requested Amount')
    no_of_times_sent = fields.Integer("# of Times Sent")
    default_card_id = fields.Integer(string='Default Credit Card ID')

    def resend_email(self):
        try:
            resp_lines = []
            success = 0
            failed = 0
            total_count = len(self)
            ebiz_obj = self.env['ebiz.charge.api']
            for record in self:
                invoice_id = record.invoice_id
                resp_line = {'customer_name': invoice_id.partner_id.id, 'customer_id': invoice_id.partner_id.id,
                             'invoice_id': invoice_id.id, 'email': record.email_id}
                instance = invoice_id.partner_id.ebiz_profile_id or None
                ebiz = ebiz_obj.get_ebiz_charge_obj(instance=instance)
                ebiz.client.service.ResendEbizWebFormEmail(**{
                    'securityToken': ebiz._generate_security_json(),
                    'paymentInternalId': invoice_id.payment_internal_id,
                })
                invoice_id.no_of_times_sent += 1
                record.no_of_times_sent = invoice_id.no_of_times_sent
                resp_line['status'] = 'Success'
                resp_line['should_show_icon'] = False
                success += 1
                resp_lines.append(fields.Command.create(resp_line))
            wizard = self.env['wizard.email.pay.message'].create(
                {'name': 'resend_email_pay', 'lines_ids': resp_lines,
                 'success_count': success,
                 'failed_count': failed,
                 'total': total_count})

            return {'type': 'ir.actions.act_window',
                    'name': _('Email Pay for Invoices'),
                    'res_model': 'wizard.email.pay.message',
                    'target': 'new',
                    'res_id': wizard.id,
                    'view_mode': 'form',
                    'views': [[False, 'form']],
                    'context': self.env.context,
                    }

        except Exception as e:
            if e.args[0] == 'Error: Object reference not set to an instance of an object.':
                raise UserError('This Invoice Either Paid Or Deleted!')
            raise UserError(e)

    def delete_invoice(self):
        try:
            text = f"Are you sure you want to remove {len(self)} request(s) from Pending Requests?"
            wizard = self.env['wizard.delete.email.pay'].create({"record_id": self.sync_transaction_id_pending.id,
                                                                 "record_model": 'sync.request.payments.bulk.pending',
                                                                 "text": text})
            action = self.env.ref('payment_ebizcharge_crm.wizard_delete_email_pay_action').read()[0]
            action['res_id'] = wizard.id
            action['context'] = dict(
                self.env.context,
                selected_line_ids=self.ids,
                pending_received='Pending Requests'
            )
            return action

        except Exception as e:
            raise UserError(e)


class ListReceivedBulkInvoices(models.Model):
    _name = 'sync.request.payments.bulk.received'
    _order = 'date_time asc'
    _description = "Sync Request Payments Bulk Received"

    sync_date = fields.Datetime('Execution Date/Time', required=True, default=fields.Datetime.now)
    sync_transaction_id_received = fields.Many2one('payment.request.bulk.email', string='Partner Reference',
                                                   required=True,
                                                   ondelete='cascade', index=True, copy=False)
    name = fields.Char(string='Number')
    customer_id = fields.Many2one('res.partner', string='Customer')
    invoice_id = fields.Many2one('account.move', string='Invoice')
    account_holder = fields.Char(string='Account Holder')
    currency_id = fields.Many2one('res.currency', string='Company Currency')
    date_time = fields.Datetime(string='Date Time')
    amount = fields.Float(string='Invoice Total')
    amount_due = fields.Float(string='Amount Due')
    tax = fields.Float(string='Tax Excluded')
    card_no = fields.Char(string='Card Number')
    status = fields.Char(string='Status')
    email_id = fields.Char(string='Email ID')
    invoice_date = fields.Date(string='Invoice Date')
    sales_person = fields.Many2one('res.users', string='Sales Person')
    payment_method = fields.Char('Payment Method')
    paid_amount = fields.Float('Amount Paid')
    ref_num = fields.Char('Reference Number')
    payment_request_date_time = fields.Datetime('Date & Time Paid')

    def _prepare_invoice_update_values(self, invoice_status):
        return {
            'ebiz_invoice_status': invoice_status,
            'receipt_ref_num': self.ref_num,
            'save_payment_link': False,
            'is_payment_processed': True,
            'request_amount': 0,
            'last_request_amount': 0,
            'ebiz_payment_link': 'applied'
        }

    def _prepare_move_receipts_values(self):
        return {
            'invoice_id': self.invoice_id.id,
            'name': self.env.user.currency_id.symbol + str(self.paid_amount) + ' Paid On ' +
                    self.payment_request_date_time.strftime('%Y-%m-%d'),
            'ref_nums': self.ref_num,
            'model': '[\'account.move\', \'ebiz.charge.api\']',
        }

    def _prepare_payment_values(self, journal_id, ebiz_method, payment_reference='', memo=''):
        return {
            'journal_id': journal_id.id,
            'payment_method_id': ebiz_method.payment_method_id.id,
            'payment_method_line_id': ebiz_method.id,
            'amount': float(self.paid_amount),
            'token_type': None,
            'partner_id': self.customer_id.id,
            'payment_reference': payment_reference,
            'payment_type': 'inbound',
            'memo': memo
        }

    def mark_applied(self):
        try:
            for record in self:
                invoice_id = record.invoice_id
                if invoice_id:
                    if invoice_id.state == 'draft':
                        invoice_id.action_post()

                    if invoice_id['amount_residual'] - float(record.paid_amount) > 0:
                        invoice_id.write(record._prepare_invoice_update_values('partially_received'))
                    else:
                        invoice_id.write(record._prepare_invoice_update_values('received'))

                    self.env['account.move.receipts'].create(record._prepare_move_receipts_values())
                    journal_id = False
                    payment_acq = self.env['payment.provider'].search(
                        [('company_id', '=', invoice_id.company_id.id), ('code', '=', 'ebizcharge')])
                    if payment_acq and payment_acq.state == 'enabled':
                        journal_id = payment_acq.journal_id

                    if journal_id:
                        ebiz_method = self.env['account.payment.method.line'].search(
                            [('journal_id', '=', payment_acq.journal_id.id),
                             ('payment_method_id.code', '=', 'ebizcharge')], limit=1)
                        if invoice_id.state != 'cancel':
                            memo = invoice_id.name
                            if invoice_id.partner_id.ebiz_profile_id.payment_memo_setting == 'dn_pon_pm':
                                memo = " ".join(val for val in [invoice_id.name, invoice_id.ref, record.payment_method] if val)
                            payment = self.env['account.payment'].sudo().with_context(active_ids=invoice_id.ids, active_model='account.move',
                                              active_id=invoice_id.id) \
                                .create(record._prepare_payment_values(journal_id, ebiz_method, record.name, memo))
                            payment.with_context({'pass_validation': True}).action_post()
                            payment.action_validate()
                            invoice_id.with_context({'payment_id': payment.id}).reconcile()
                            invoice_id.sync_to_ebiz()
                        else:
                            payment = self.env['account.payment'].sudo().create(record._prepare_payment_values(journal_id, ebiz_method))
                            payment.with_context({'pass_validation': True}).action_post()
                        if invoice_id.amount_residual <= 0 and invoice_id.state != 'cancel':
                            invoice_id.mark_as_applied()
                        else:
                            instance = invoice_id.partner_id.ebiz_profile_id or None
                            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
                            ebiz.client.service.MarkEbizWebFormPaymentAsApplied(**{
                                'securityToken': ebiz._generate_security_json(),
                                'paymentInternalId': invoice_id.payment_internal_id,

                            })
                            received_payments = self.env['payment.request.bulk.email'].search([])
                            for payment in received_payments:
                                if payment.transaction_history_line_received:
                                    for pending in payment.transaction_history_line_received:
                                        if pending.invoice_id == record.invoice_id:
                                            payment.transaction_history_line_received = [fields.Command.delete(pending.id)]
                    else:
                        raise UserError('EBizCharge Journal Not Found!')

            self.sync_transaction_id_received.regenerate_line_ids()
            return message_wizard('Received payment(s) applied successfully!')

        except Exception as e:
            raise ValidationError(e)

    def delete_invoice_received(self):
        try:
            text = f"Are you sure you want to remove {len(self)} payment(s) from Received Email Payments?"
            wizard = self.env['wizard.delete.email.pay'].create({"record_id": self.sync_transaction_id_received.id,
                                                                 "record_model": 'sync.request.payments.bulk.received', "text": text})
            action = self.env.ref('payment_ebizcharge_crm.wizard_delete_email_pay_action').read()[0]
            action['res_id'] = wizard.id
            action['context'] = dict(
                self.env.context,
                selected_line_ids=self.ids,
                pending_received='Received Email Payments'
            )
            return action
        except Exception as e:
            raise UserError(e)
