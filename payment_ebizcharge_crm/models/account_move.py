# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import models, fields, api, _
from odoo.exceptions import UserError,ValidationError
from datetime import datetime, timedelta
import logging
from .ebiz_charge import message_wizard
from odoo.addons.payment_ebizcharge_crm.tools import _prepare_billing_address, _transaction_lines

_logger = logging.getLogger(__name__)


class AccountMoveInh(models.Model):
    _inherit = 'account.move'


    def _get_default_ebiz_auto_sync(self):
        profile = self.partner_id.ebiz_profile_id
        return profile.ebiz_auto_sync_invoice if profile else False

    def _get_default_ebiz_auto_sync_credit_note(self):
        profile = self.partner_id.ebiz_profile_id
        return profile.ebiz_auto_sync_credit_notes if profile else False

    def _compute_ebiz_auto_sync(self):
        for rec in self:
            rec.ebiz_auto_sync = False

    def _compute_ebiz_auto_sync_credit_note(self):
        for rec in self:
            rec.ebiz_auto_sync_credit_note = False

    def _compute_receipt_status(self):
        for rec in self:
            rec.receipt_status = bool(self.env['account.move.receipts'].search([('invoice_id', '=', rec.id)]))

    ebiz_auto_sync = fields.Boolean(compute="_compute_ebiz_auto_sync", default=_get_default_ebiz_auto_sync)
    ebiz_auto_sync_credit_note = fields.Boolean(compute="_compute_ebiz_auto_sync_credit_note",
                                                default=_get_default_ebiz_auto_sync_credit_note)
    ebiz_internal_id = fields.Char(string='EBizCharge Internal Id', copy=False)
    done_transaction_ids = fields.Many2many('payment.transaction', compute='_compute_done_transaction_ids',
                                            string='Done Authorized Transactions', copy=False, readonly=True)
    is_refund_processed = fields.Boolean(default=False)
    is_payment_processed = fields.Boolean(default=False, copy=False)
    payment_internal_id = fields.Char(string='EBizCharge Email Response', copy=False)

    log_status_emv = fields.Char(string="Logs EMV", tracking=True, copy=False)
    emv_transaction_id = fields.Many2one('emv.device.transaction', string='Transaction ID', copy=False)
    ebiz_invoice_status = fields.Selection([
        ('default', ''),
        ('pending', 'Pending'),
        ('received', 'Received'),
        ('partially_received', 'Partially Received'),
        ('delete', 'Deleted'),
        ('applied', 'Applied'),
    ], string='Email Pay Status', default='default', readonly=True, copy=False, index=True)

    receipt_ref_num = fields.Char(string='Receipt RefNum')
    sync_status = fields.Char(string="EBizCharge Upload Status", compute="_compute_sync_status")
    sync_response = fields.Char(string="Sync Status", copy=False)
    last_sync_date = fields.Datetime(string="Upload Date & Time", copy=False)
    receipt_status = fields.Boolean(compute="_compute_receipt_status", default=False)
    credit_note_ids = fields.One2many('account.move', 'reversed_entry_id', string='Credit Notes')

    date_time_sent_for_email = fields.Datetime('Date & Time Sent')
    customer_id = fields.Char(string="Customer ID", compute="_compute_customer_id")
    email = fields.Char(string="Email", compute="_compute_customer_id")
    default_payment_method_name = fields.Char(string="Payment Method Name", compute="_compute_customer_id")
    default_payment_method_id = fields.Integer(string="Default Payment Method", compute="_compute_customer_id")
    email_for_pending = fields.Char(string='Email Pay Pending')
    email_received_payments = fields.Boolean(string='Email Pay Received Payments', default=False, copy=False)
    email_requested_amount = fields.Float(string='Requested Amount')
    no_of_times_sent = fields.Integer(string='# of Times Sent')
    save_payment_link = fields.Char(string='Save Payment Link', copy=False)
    odoo_payment_link = fields.Boolean(string='Payment Link', copy=False)
    request_amount = fields.Float(string='Request Amount' ,copy=False)
    last_request_amount = fields.Float(string='Last Request Amount', copy=False)
    odoo_payment_link_doc = fields.Char(string='Payment Link Doc', copy=False)
    is_email_request = fields.Boolean(string='Email Pay sent', copy=False)
    ebiz_payment_link = fields.Selection([
        ('default', ''),
        ('pending', 'Pending'),
        ('received', 'Received'),
        ('applied', 'Applied'),
    ], string='Pay link Status', default='default', readonly=True, copy=False, index=True)
    inv_enable_sur = fields.Boolean(string='Enable Surcharge')
    was_inv_sur_enabled = fields.Boolean(string='Was Surcharge Enabled')

    def _log_pay_link(self):
        for line in self:
            if line.odoo_payment_link_doc:
                line.message_post(
                    body=Markup(
                        'New Payment Link has been generated: <a href="%s" target="_blank">%s</a>' % (
                            line.odoo_payment_link_doc, line.odoo_payment_link_doc)
                    ),
                    message_type="comment",
                )


    @api.depends('partner_id', 'partner_id.email')
    def _compute_customer_id(self):
        """
           Computing customer information on invoice.
        """
        for inv in self:
            token = inv.partner_id.get_default_token()
            inv.customer_id = inv.partner_id.id
            inv.email = inv.partner_id.email
            inv.default_payment_method_name = token.display_name if token else 'N/A'
            inv.default_payment_method_id = token.id if token else 0

    @api.depends('ebiz_internal_id')
    def _compute_sync_status(self):
        """
            Computing invoice's sync status.
        """
        for order in self:
            order.sync_status = "Synchronized" if order.ebiz_internal_id else "Pending"

    @api.depends('transaction_ids')
    def _compute_done_transaction_ids(self):
        """
          Computing done transactions.
        """
        for trans in self:
            trans.done_transaction_ids = trans.transaction_ids.filtered(lambda t: t.state == 'done')

    def _get_ebiz_client(self):
        return self.env['ebiz.charge.api'].get_ebiz_charge_obj(
            instance=self.partner_id.ebiz_profile_id or None
        )

    def _get_ebiz_instance(self):
        if self.partner_id.ebiz_profile_id:
            return self.partner_id.ebiz_profile_id
        return self.env['ebizcharge.instance.config'].search(
            [('is_valid_credential', '=', True), ('is_default', '=', True), ('is_active', '=', True)],
            limit=1) or None

    @staticmethod
    def _get_ebiz_date_range(days_back=365):
        today = datetime.now()
        return today - timedelta(days=days_back), today + timedelta(days=1)

    def _get_ebiz_journal_and_method(self, company=None):
        company = company or self.company_id
        acquirer = self.env['payment.provider'].search(
            [('company_id', '=', company.id), ('code', '=', 'ebizcharge'), ('state', '=', 'enabled')])
        journal = acquirer.journal_id
        method_line = self.env['account.payment.method.line'].search(
            [('journal_id', '=', journal.id), ('payment_method_id.code', '=', 'ebizcharge')], limit=1)
        return journal, method_line

    def _build_payment_memo(self, *extra_parts):
        if self.partner_id.ebiz_profile_id.payment_memo_setting == 'dn_pon_pm':
            return " ".join(val for val in [self.name, self.ref, *extra_parts] if val)
        return self.name

    def js_update_enable_sur(self, **kwargs):
        if self.exists():
            self.write({'inv_enable_sur': kwargs.get('enable_sur')})
            if kwargs.get('res_id'):
                wizard_id = self.env['account.payment.register'].browse(kwargs.get('res_id')).exists()
                wizard_id._onchange_enable_surcharge()

    def action_post(self):
        ret = super(AccountMoveInh, self.with_context({'from_post': True})).action_post()
        payment_method_codes = self.line_ids.payment_id.payment_method_line_id.mapped('code')
        if payment_method_codes and 'ebizcharge' not in payment_method_codes:
            return ret
        for invoice in self:
            if not invoice.partner_id.ebiz_profile_id:
                continue
            profile = invoice.partner_id.ebiz_profile_id
            if invoice.partner_id.customer_rank > 0:
                if invoice.move_type == 'out_invoice' and profile.ebiz_auto_sync_invoice:
                    invoice.sync_to_ebiz()
                elif invoice.move_type == 'out_refund' and profile.ebiz_auto_sync_credit_notes:
                    invoice.sync_to_ebiz()
                elif invoice.move_type in ('out_invoice', 'out_refund') and invoice.ebiz_internal_id and not invoice.done_transaction_ids:
                    invoice.sync_to_ebiz()
            invoice._auto_capture_on_post()
            invoice._handle_deposit_payment()
            if not invoice.save_payment_link and invoice.amount_residual > 0 and profile.invoice_auto_gpl and invoice.sale_order_count == 0 and invoice.payment_state not in ('in_payment', 'paid'):
                invoice.action_generate_pay_ebiz_link()
        return ret

    def _auto_capture_on_post(self):
        txn = self.authorized_transaction_ids
        if not txn:
            return
        if not all([
            self.partner_id.ebiz_profile_id.apply_sale_pay_inv,
            txn[0].provider_id.code == 'ebizcharge',
            not txn[0].emv_transaction,
        ]):
            return
        if txn[0].child_transaction_ids.filtered(lambda t: t.state == 'done'):
            return
        self.payment_action_capture()

    def _handle_deposit_payment(self):
        txn = self.done_transaction_ids
        if not txn or txn[0].provider_id.code != 'ebizcharge':
            return
        payment = txn.payment_id
        if not payment:
            txn._post_process_transactions()
        if payment.state == 'draft':
            payment.payment_reference = self.name
            payment.action_post()
            payment.action_validate()
            self.with_context({'payment_id': payment.id}).reconcile()
        elif payment.state in ('paid', 'in_process'):
            self.with_context({'payment_id': payment.id}).reconcile()



    def _prepare_invoice_paylink_form(self, template, payment_method, command, lines):
        invoice_number = str(self.id) if str(self.name) == '/' else str(self.name)
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
            'PayByType': payment_method,
            'AmountDue': self.amount_residual,
            'ShippingAmount': 0,
            'ProcessingCommand': command,
            'CustomerId': self.partner_id.ebiz_customer_id or self.partner_id.id,
            'ShowViewInvoiceLink': True,
            'SendEmailToCustomer': False,
            'TaxAmount': self.amount_tax,
            'SoftwareId': 'ODOOPayLinkOnly',
            'InvoiceInternalId': self.ebiz_internal_id,
            'Description': 'Invoice',
            'DocumentTypeId': 'Invoice',
            'OrderId': invoice_number,
            'PoNum': self.ref or self.name,
            'InvoiceNumber': " ".join(part for part in [invoice_number, self.ref] if part)
                if self.partner_id.ebiz_profile_id.payment_memo_setting == 'dn_pon_pm' else invoice_number,
            'Date': self.invoice_date or self.invoice_date_due or '',
            'BillingAddress': _prepare_billing_address(self),
            'LineItems': _transaction_lines(lines),
        }
        if self.partner_id.ebiz_customer_id:
            form['CustomerId'] = self.partner_id.ebiz_customer_id
        return form

    def action_generate_pay_ebiz_link(self):
        template = self.env['email.templates'].search([('template_type_id', '=', 'WebFormEmail'), (
            'instance_id', '=', self.partner_id.ebiz_profile_id.id) ], limit=1)
        if template:
            ebiz = self._get_ebiz_client()
            lines = self.invoice_line_ids
            profile = self.partner_id.ebiz_profile_id
            get_merchant_data = profile.merchant_data if profile else False
            get_allow_credit_card_pay = profile.allow_credit_card_pay if profile else False
            payment_method = 'CC'
            if get_merchant_data and get_allow_credit_card_pay:
                payment_method = 'CC,ACH'
            elif get_merchant_data:
                payment_method = 'ACH'
            elif get_allow_credit_card_pay:
                payment_method = 'CC'
            command = 'Sale'
            inv_enable_sur = True
            merchant_account_id = self.partner_id.ebiz_profile_id
            check_all_for_surcharge = [merchant_account_id, merchant_account_id.is_surcharge_enabled,
                                       merchant_account_id.merchant_toggle_sur_per_txn]
            if all(check_all_for_surcharge) and not merchant_account_id.enable_sur_invoice_auto_gpl:
                command += ';IsSurchargeEnabled=false'
                inv_enable_sur = False
            ePaymentForm = self._prepare_invoice_paylink_form(template, payment_method, command, lines)
            form_url = ebiz.client.service.GetEbizWebFormURL(**{
                'securityToken': ebiz._generate_security_json(),
                'ePaymentForm': ePaymentForm
            })
            self.inv_enable_sur = inv_enable_sur
            self.save_payment_link = form_url
            self.is_email_request = False
            self.payment_internal_id = form_url.split('=')[1]

            if self.save_payment_link:
                self.message_post(
                    body=Markup(
                        'New EBizCharge Payment Link has been generated: <a href="%s" target="_blank">%s</a>' % (
                        form_url, form_url)
                    ),
                    message_type="comment",
                )

    def show_ebiz_invoice(self):
        """ Show EBizCharge invoice """
        return {
            'name': 'Go to website',
            'res_model': 'ir.actions.act_url',
            'type': 'ir.actions.act_url',
            'target': 'new',
            'url': f"https://cloudview1.ebizcharge.net/ViewInvoice1.aspx?InvoiceInternalId={self.ebiz_internal_id}"
        }

    def sync_to_ebiz(self, time_sample=None):
        update_params = {}
        self.ensure_one()
        sale_id = self.invoice_line_ids[0].sale_line_ids.order_id if self.invoice_line_ids else False
        instance = self._get_ebiz_instance()
        web_sale = self.env['ir.module.module'].sudo().search(
            [('name', '=', 'website_sale'), ('state', 'in', ['installed', 'to upgrade', 'to remove'])])
        ebiz_obj = self.env['ebiz.charge.api']
        if web_sale:
            ebiz = ebiz_obj.get_ebiz_charge_obj(
                website_id=sale_id.website_id.id if sale_id and hasattr(sale_id, 'website_id') else None, instance=instance)
        else:
            ebiz = ebiz_obj.get_ebiz_charge_obj(instance=instance)
        if not self.partner_id.ebiz_internal_id:
            self.partner_id.sync_to_ebiz()
        if self.ebiz_internal_id:
            resp = ebiz.update_invoice(self)
            if resp['Error'] == 'Not Found ':
                resp_search = False
                resp = ebiz.sync_invoice(self)
                if resp['ErrorCode'] == 2:
                    resp_search = self.ebiz_search_invoice()
                update_params.update({'ebiz_internal_id': resp['InvoiceInternalId'] or resp_search['InvoiceInternalId'],
                                      'sync_response': 'Success' if resp['ErrorCode'] in [0, 2] else resp['Error']})
            else:
                update_params = {'sync_response': resp['Error'] or resp['Status']}
        else:
            resp_search = False
            resp = ebiz.sync_invoice(self)
            if resp['ErrorCode'] == 2:
                resp_search = self.ebiz_search_invoice()
            update_params.update({'ebiz_internal_id': resp['InvoiceInternalId'] or resp_search['InvoiceInternalId'],
                                  'sync_response': 'Success' if resp['ErrorCode'] in [0, 2] else resp['Error']})
        self._create_sync_log(resp)
        update_params['last_sync_date'] = fields.Datetime.now()
        self.write(update_params)
        return resp

    def _create_sync_log(self, resp):
        logs_dict = self.get_log_dict(resp)
        if self.move_type == 'out_refund':
            self.env['logs.credit.notes'].create(logs_dict)
        else:
            self.env['ebiz.log.invoice'].create(logs_dict)


    def get_log_dict(self, resp):
        return {
            'invoice': self.id,
            'partner_id': self.partner_id.id,
            'sync_status': 'Success' if resp['ErrorCode'] in [0, 2] else resp['Error'],
            'last_sync_date': datetime.now(),
            'currency_id': self.env.user.currency_id.id,
            'amount_untaxed': self.amount_untaxed_signed,
            'amount_total_signed': self.amount_total,
            'amount_residual_signed': self.amount_residual,
            'invoice_date_due': self.invoice_date_due,
            'invoice_date': self.invoice_date,
            'name': self.name,
        }

    def process_invoices(self, send_receipt):
        try:
            message_lines = []
            for record in self:
                record.sync_to_ebiz()
                record.ebiz_batch_procssing_reg(record.default_payment_method_id, send_receipt)
                message_lines.append(fields.Command.create({
                    'customer_id': record.customer_id,
                    'customer_name': record.partner_id.name,
                    'invoice_no': record.name,
                    'status': record.transaction_ids.state,
                }))
            self.create_log_lines()
            wizard = self.env['batch.process.message'].create({'name': "Batch Process", 'lines_ids': message_lines})
            action = self.env.ref('payment_ebizcharge_crm.wizard_batch_process_message_action').read()[0]
            action['context'] = self.env.context
            action['res_id'] = wizard.id
            return action

        except Exception as e:
            _logger.exception(e)
            raise UserError(e)

    def create_log_lines(self):
        list_of_invoices = []
        for invoice in self:
            if not invoice.transaction_ids:
                continue
            partner = invoice.partner_id
            transaction_id = invoice.transaction_ids[0]
            dict1 = {
                "name": invoice['name'],
                "customer_name": partner.id,
                "customer_id": partner.id,
                "date_paid": transaction_id.date,
                "currency_id": invoice.currency_id.id,
                "amount_paid": invoice.amount_total,
                "transaction_status": transaction_id.state,
                "payment_method": invoice.default_payment_method_name,
                "auth_code": transaction_id.ebiz_auth_code,
                "transaction_ref": transaction_id.provider_reference,
                'email': invoice.email,
            }
            list_of_invoices.append(dict1)
        self.env['sync.batch.log'].search([]).unlink()
        self.env['sync.batch.log'].create(list_of_invoices)

    def sync_to_ebiz_invoice(self):
        if self.move_type == "out_invoice":
            self.sync_to_ebiz()
            return message_wizard('Invoice uploaded successfully!')
        else:
            return False

    def sync_to_ebiz_credit_note(self):
        if self.move_type == "out_refund":
            self.sync_to_ebiz()
            return message_wizard('Credit Note uploaded successfully!')
        else:
            return False

    def ebiz_search_invoice(self):
        ebiz = self._get_ebiz_client()
        resp = ebiz.client.service.SearchInvoices(**{
            'securityTokenCustomer': ebiz._generate_security_json(),
            'customerId': self.partner_id.id,
            'invoiceNumber': self.name,
            'start': 0,
            'limit': 0,
            'includeItems': False
        })
        if resp:
            return resp[0]
        return resp

    def action_register_payment(self):
        for line in self:
            if line.emv_transaction_id:
                line.emv_transaction_id.action_check(trans=line.emv_transaction_id.id)
        ret = super().action_register_payment()
        check = any(inv.save_payment_link for inv in self)
        for line in self:
            if line.ebiz_internal_id:
                ebiz = line._get_ebiz_client()
                from_date = datetime.strftime((line.create_date - timedelta(days=1)), '%Y-%m-%dT%H:%M:%S')
                to_date = datetime.strftime((datetime.now() + timedelta(days=1)), '%Y-%m-%dT%H:%M:%S')
                params = {
                    'securityToken': ebiz._generate_security_json(),
                    "fromDateTime": from_date,
                    "toDateTime": to_date,
                    "customerId": line.partner_id.id,
                    "limit": 1000,
                    "start": 0,
                }
                payments = ebiz.client.service.GetPayments(**params)
                payments = list(filter(lambda x: x['InvoiceNumber'] == line.name, payments or []))
                if payments:
                    for payment in payments:
                        line.ebiz_create_payment_line(payment['PaidAmount'])
                        resp = ebiz.client.service.MarkPaymentAsApplied(**{
                            'securityToken': ebiz._generate_security_json(),
                            'paymentInternalId': payment['PaymentInternalId'],
                            'invoiceNumber': line.name
                        })
                    inv_type = 'invoice' if line.move_type == 'out_invoice' else 'credit note'
                    return message_wizard(f'This {inv_type} has already been processed on the EBizCharge portal!')
        if line.partner_id.ebiz_profile_id and line.partner_id.ebiz_profile_id.is_emv_enabled:
            line.partner_id.ebiz_profile_id.action_get_devices()
        ret['context'].update({
            'default_is_pay_link': check
        })
        return ret

    def action_reverse(self):
        if not self.env.context.get('bypass_credit_note_restriction'):
            total_credit_amount = sum(self.credit_note_ids.mapped('amount_total'))
            if self.amount_total <= total_credit_amount:
                params = {
                    "invoice_id": self.id,
                    "text": "You have already given the customer credit for the full amount of invoice. Do you want "
                            "to give more credit to customer against this invoice?"
                }
                wiz = self.env['wizard.credit.note.validate'].create(params)
                action = self.env.ref('payment_ebizcharge_crm.wizard_credit_note_validate_action').read()[0]
                action['res_id'] = wiz.id
                return action

        action = super().action_reverse()
        if self.env.context.get('active_model') == 'account.move':
            action['context'] = dict(self.env.context)
        return action

    def run_ebiz_transaction(self, payment_token_id, command, card=None, token_ebiz=None):
        self.ensure_one()
        if not self.partner_id.ebiz_internal_id and payment_token_id and payment_token_id.partner_id.id==self.partner_id.id:
            self.partner_id.sync_to_ebiz()
        instance = (
            (payment_token_id and payment_token_id.partner_id.ebiz_profile_id)
            or self.partner_id.ebiz_profile_id
            or self.env.user.partner_id.ebiz_profile_id
            or self.env['ebizcharge.instance.config'].search(
                [('is_valid_credential', '=', True), ('is_default', '=', True)], limit=1)
        )

        ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
        if self.env.context.get('run_transaction'):
            resp = ebiz.run_full_amount_transaction(self, payment_token_id, command, card, token_ebiz=token_ebiz)
        else:
            resp = ebiz.run_customer_transaction(self, payment_token_id, command, current_user=self.env.user.partner_id)
        return resp


    def payment_action_capture(self):
        if not (self.authorized_transaction_ids
                and self.authorized_transaction_ids[0].provider_id.code == 'ebizcharge'):
            return super().payment_action_capture()

        auth_tx = self.authorized_transaction_ids[0]
        ctx = {'from_invoice': True, 'invoice_id': self}
        if auth_tx.emv_transaction:
            ctx['emv_trans'] = self.authorized_transaction_ids

        ret = super(AccountMoveInh, self.with_context(ctx)).payment_action_capture()

        child_done_txs = auth_tx.child_transaction_ids.filtered(
            lambda t: t.state == 'done' and not t.payment_id
        )
        (child_done_txs or auth_tx).with_context({'invoice_id': self})._post_process_transactions()

        if self.payment_state == 'not_paid':
            self.reconcile()
        return ret


    def payment_action_void(self):
        ret = super().payment_action_void()
        receipt_check = self.env['account.move.receipts'].search([('invoice_id', '=', self.id)])
        if receipt_check:
            receipt_check[-1].unlink()
        return ret

    def ebiz_create_payment_line(self, amount, payment_method=False):
        journal_id, ebiz_method = self._get_ebiz_journal_and_method()
        memo = self._build_payment_memo(payment_method)
        payment = self.env['account.payment'] \
            .sudo().with_context(active_ids=self.ids, active_model='account.move', active_id=self.id) \
            .create({'journal_id': journal_id.id,
                     'payment_method_id': ebiz_method.payment_method_id.id,
                     'payment_method_line_id':ebiz_method.id,
                     'token_type': None,
                     'amount': amount,
                     'partner_id': self.partner_id.id,
                     'transaction_ref': self.name or None,
                     'payment_reference': self.name or None,
                     'memo': memo,
                     'payment_type': 'outbound' if self.move_type == 'out_refund' else 'inbound'
                     })
        payment.with_context({'do_not_run_transaction': True}).action_post()
        self.with_context({'payment_id': payment.id}).reconcile()
        self.write({'ebiz_invoice_status': 'partially_received' if self.amount_residual else 'received',
                    'is_payment_processed': True})
        if self.save_payment_link:
            self.write({'request_amount': self.amount_residual, 'last_request_amount': 0,
                        'ebiz_payment_link': 'applied', 'save_payment_link': False})
            instance = self.partner_id.ebiz_profile_id
            if self.payment_internal_id and instance:
                ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
                ebiz.client.service.DeleteEbizWebFormPayment(**{
                    'securityToken': ebiz._generate_security_json(),
                    'paymentInternalId': self.payment_internal_id,
                })
        return super(AccountMoveInh, self).payment_action_capture()

    def ebiz_batch_procssing_reg(self, default_card_id, ebiz_send_receipt):
        journal_id, ebiz_method = self._get_ebiz_journal_and_method()
        if not journal_id:
            raise UserError('There is no Acquirer link to this ' + self.company_id.name + '.')
        token = self.env['payment.token'].browse(default_card_id)
        memo = self._build_payment_memo(token.get_encrypted_name())
        payment = self.env['account.payment'] \
            .sudo().with_context(active_ids=self.ids, active_model='account.move', active_id=self.id) \
            .create({'journal_id': journal_id.id,
                     'card_id': default_card_id if token.token_type == "credit" else None,
                     'ach_id': default_card_id if token.token_type == "ach" else None,
                     'payment_token_id': default_card_id,
                     'token_type': token.token_type,
                     'amount': self.amount_residual_signed,
                     'transaction_command': 'Sale',
                     'ebiz_send_receipt': ebiz_send_receipt,
                     'ebiz_receipt_emails': self.partner_id.email,
                     'payment_method_id': ebiz_method.payment_method_id.id,
                     'payment_method_line_id': ebiz_method.id,
                     'partner_id': self.partner_id.id,
                     'payment_reference': self.name or None,
                     'payment_type': 'inbound',
                     'memo': memo
                     })
        payment.sudo().with_context({'payment_data': {
            'token_type': token.token_type,
            'card_id': token if token.token_type == "credit" else None,
            'ach_id': token if token.token_type == "ach" else None,
            'card_card_number': payment.card_card_number,
            'security_code': False,
            'ebiz_send_receipt': ebiz_send_receipt,
            'ebiz_receipt_emails': self.partner_id.email,
        }, 'batch_processing': True, 'active_ids': self.ids, 'active_model': 'account.move', 'active_id': self.id}).action_post()
        if payment.state == 'posted':
            self.with_context({'payment_id': payment.id}).reconcile()
            self.write({'ebiz_invoice_status': 'partially_received' if self.amount_residual else 'received',
                        'is_payment_processed': True})
        return super(AccountMoveInh, self).payment_action_capture()

    def process_refund_payment(self):
        journal_id, ebiz_method = self._get_ebiz_journal_and_method()

        payment_method_id = self.env['account.payment.method'].search([('code', '=', 'electronic')]).id
        payment = self.env['account.payment'] \
            .sudo().with_context(active_ids=self.ids, active_model='account.move', active_id=self.id) \
            .create({'journal_id': journal_id.id, 'payment_method_id': ebiz_method.payment_method_id.id, 'payment_method_line_id':ebiz_method.id})
        payment.with_context({'pass_validation': True}).action_post()

    def _build_sync_result_lines(self, invoice_records):
        resp_lines = []
        success = 0
        failed = 0
        for inv in invoice_records:
            resp_line = {
                'customer_name': inv.partner_id.name,
                'customer_id': inv.partner_id.id,
                'invoice_number': inv.name,
            }
            try:
                resp = inv.sync_to_ebiz()
                resp_line['record_message'] = resp['Error'] or resp['Status']
            except Exception as e:
                _logger.exception(e)
                resp_line['record_message'] = str(e)
            if resp_line['record_message'] in ('Success', 'Record already exists'):
                success += 1
            else:
                failed += 1
            resp_lines.append(fields.Command.create(resp_line))
        return resp_lines, success, failed, len(invoice_records)

    def _open_sync_result_wizard(self, resp_lines, success, failed, total, name='invoices'):
        wizard = self.env['wizard.multi.sync.message'].create({
            'name': name,
            'invoice_lines_ids': resp_lines,
            'success_count': success,
            'failed_count': failed,
            'total': total,
        })
        action = self.env.ref('payment_ebizcharge_crm.wizard_multi_sync_message_action').read()[0]
        action['context'] = self.env.context
        action['res_id'] = wizard.id
        return action

    def ebiz_sync_multiple_invoices(self):
        resp_lines, success, failed, total = self._build_sync_result_lines(self)
        return self._open_sync_result_wizard(resp_lines, success, failed, total)

    def sync_multi_customers_from_upload_invoices(self, invoice_ids):
        invoice_records = self.env['account.move'].browse(invoice_ids).exists()
        resp_lines, success, failed, total = self._build_sync_result_lines(invoice_records)
        name = 'credit_notes' if self.env.context.get('credit') == 'credit_notes' else 'invoices'
        return self._open_sync_result_wizard(resp_lines, success, failed, total, name)

    def write(self, values):
        ret = super(AccountMoveInh, self).write(values)
        if self._ebiz_check_invoice_update(values):
            for invoice in self:
                if invoice.ebiz_internal_id and invoice.partner_id.customer_rank > 0:
                    invoice.sync_to_ebiz()
        return ret

    def email_invoice_ebiz(self):
        try:

            if self.ebiz_invoice_status == 'pending':
                raise UserError(f'An email pay request has already been sent.')

            if self.state == 'draft':
                self.action_post()

            if not self.ebiz_internal_id:
                self.sync_to_ebiz()


            if self.save_payment_link:
                ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=self._get_ebiz_instance())
                start, end = self._get_ebiz_date_range()

                received_payments = ebiz.client.service.SearchEbizWebFormReceivedPayments(**{
                    'securityToken': ebiz._generate_security_json(),
                    'fromPaymentRequestDateTime': str(start.date()),
                    'toPaymentRequestDateTime': str(end.date()),
                    'start': 0,
                    'limit': 10000,
                })

                if received_payments:
                    for invoice in received_payments:
                        odoo_invoice = self.env['account.move'].search(
                            [('payment_internal_id', '=', invoice['PaymentInternalId'])])
                        try:
                            if odoo_invoice and odoo_invoice.id == self.id:
                                text = f"There is a payment of {self.env.user.company_id.currency_id.symbol}{float(invoice['PaidAmount'])} received on this {self.name}.\nWould you like to apply this payment?"
                                wizard = self.env['wizard.receive.email.pay'].create({"record_id": self.id,
                                                                                      "odoo_invoice": odoo_invoice.id,
                                                                                      "text": text})
                                action = self.env.ref('payment_ebizcharge_crm.wizard_recieved_email_pay').read()[0]
                                action['res_id'] = wizard.id
                                action['context'] = dict(
                                    invoice=invoice,
                                )
                                return action
                            else:
                                continue
                        except Exception:
                            _logger.exception("Failed to build received-payment wizard for invoice %s", self.id)
                    else:
                        text = f"This document has an existing payment link. Proceeding will invalidate the existing link. Do you want to continue?"
                        wizard = self.env['wizard.receive.email.payment.link'].create({
                                                                                       "odoo_invoice": self.id,
                                                                                       "text": text})
                        action = self.env.ref('payment_ebizcharge_crm.wizard_received_email_pay_payment_link').read()[0]
                        action['res_id'] = wizard.id
                        action['context'] = dict(
                            invoice=invoice,
                            email_pay=True,
                        )
                        return action
            if self.odoo_payment_link:
                text = f"This document has a pending payment link. Proceeding may increase the risk of double payments. Do you want to continue?"
                wizard = self.env['wizard.receive.email.payment.link'].create({
                                                                               "odoo_invoice": self.id,
                                                                               "text": text})
                action = self.env.ref('payment_ebizcharge_crm.wizard_received_email_pay_payment_link').read()[0]
                action['res_id'] = wizard.id
                action['context'] = dict(
                    invoice=self.id,
                    email_pay=True,
                )
                return action

            return {'type': 'ir.actions.act_window',
                    'name': _('Email Pay Request'),
                    'res_model': 'email.invoice',
                    'target': 'new',
                    'view_mode': 'form',
                    'view_type': 'form',
                    'context': {
                        'default_contacts_to': [fields.Command.set([self.partner_id.id])],
                        'default_partner_ids': [fields.Command.set([self.partner_id.id])],
                        'default_record_id': self.id,
                        'default_ebiz_profile_id': self.partner_id.ebiz_profile_id.id,
                        'default_currency_id': self.currency_id.id,
                        'default_amount': self.amount_residual if self.amount_residual else self.amount_total,
                        'default_model_name': str(self._inherit),
                        'default_email_customer': str(self.partner_id.email if self.partner_id.email else ''),
                        'selection_check': 1,
                    },
                    }

        except Exception as e:
            raise ValidationError(e)

    def resend_email_invoice_ebiz(self):
        try:
            ebiz = self._get_ebiz_client()
            form_url = ebiz.client.service.ResendEbizWebFormEmail(**{
                'securityToken': ebiz._generate_security_json(),
                'paymentInternalId': self.payment_internal_id,
            })

            self.no_of_times_sent += 1
            return message_wizard('Email pay request has been successfully resent!')

        except Exception as e:
            if e.args[0] == 'Error: Object reference not set to an instance of an object.':
                raise UserError('This Invoice Either Paid Or Deleted!')
            raise UserError(e)


    def get_payments_sales_apply(self,instance=None):
        ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
        params = {
            'securityToken': ebiz._generate_security_json(),
            "filters": {'SearchFilter': {'FieldName': 'SoftwareId', 'ComparisonOperator': 'eq',
                                         'FieldValue': 'IOSMobileApp'}, },
            "countOnly": False,
            "limit": 1000,
            "start": 0,
        }
        payments = ebiz.client.service.SearchApplicationTransactions(**params)
        payment_lines = []

        def ref_date(date):
            if not date:
                return date
            if '-' in date:
                rf_date = date.split('-')
            else:
                rf_date = date.split('/')
            return f"{rf_date[1]}/{rf_date[2]}/{rf_date[0]}"

        if payments:
            for payment in payments['ApplicationTransactions']['ApplicationTransactionDetails']:
                if 'CustomerInternalId' in payment and payment['CustomerInternalId'] != 'False':
                    odooCustomer = self.env['res.partner'].search(
                        [('ebiz_internal_id', '=', payment['CustomerInternalId'])], limit=1)
                    if odooCustomer:
                        currency_id = odooCustomer.property_product_pricelist.currency_id.id
                        saleordrr = self.env['sale.order'].search([('name', '=', payment['LinkedToExternalUniqueId'])], limit=1)
                        if saleordrr:
                            if saleordrr:
                                resp = ebiz.client.service.MarkApplicationTransactionAsApplied(**{
                                    'securityToken': ebiz._generate_security_json(),
                                    'applicationTransactionInternalId': payment['ApplicationTransactionInternalId'],
                                })

                                if resp and resp['Status'] == 'Success':
                                    journal, ebiz_method = self._get_ebiz_journal_and_method(
                                        company=odooCustomer.company_id or self.env.company)
                                    payment = self.env['account.payment'].sudo().create({
                                        'journal_id': journal.id,
                                        'payment_method_id': ebiz_method.payment_method_id.id,
                                        'payment_method_line_id':ebiz_method.id,
                                        'partner_id': odooCustomer.id,
                                        'payment_reference': payment['TransactionId'],

                                        'amount': float(payment['TransactionAmount'] or "0"),
                                        'partner_type': 'customer',
                                        'payment_type': 'inbound',
                                        'transaction_ref': payment['LinkedToExternalUniqueId'] if payment['LinkedToExternalUniqueId'] else '',
                                    })
                                    payment.action_post()

    def get_pending_invoices(self, instance=None):
        """Get received payments paid via email invoice and change their status."""
        try:
            instance = instance or self.partner_id.ebiz_profile_id
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
            start, end = self._get_ebiz_date_range()

            filters_list = []
            if 'for_pay_link' in self.env.context and self.ebiz_invoice_status != 'pending':
                filters_list.append({'FieldName': 'FormType', 'ComparisonOperator': 'eq', 'FieldValue': 'PayLinkOnly'})

            self._apply_web_form_payments(ebiz, start, end, filters_list)

            if 'for_pay_link' not in self.env.context:
                self._apply_quick_payments(ebiz, start, end)
                self._apply_recurring_payments(ebiz, start, end)

        except Exception as e:
            raise UserError(e)

    def _apply_web_form_payments(self, ebiz, start, end, filters_list):
        received_payments = ebiz.client.service.SearchEbizWebFormReceivedPayments(**{
            'securityToken': ebiz._generate_security_json(),
            'fromPaymentRequestDateTime': str(start.date()),
            'toPaymentRequestDateTime': str(end.date()),
            'start': 0,
            'limit': 10000,
            "filters": {'SearchFilter': filters_list},
        })
        if not received_payments:
            return
        for invoice in received_payments:
            try:
                odoo_invoice = self.env['account.move'].search([
                    ('payment_internal_id', '=', invoice['PaymentInternalId']),
                    '|',
                    ('ebiz_invoice_status', 'in', ['pending']),
                    ('ebiz_payment_link', 'in', ['received']),
                ])
                if not odoo_invoice:
                    continue
                if odoo_invoice.state != 'posted':
                    odoo_invoice.action_post()
                status = 'partially_received' if odoo_invoice['amount_residual'] - float(invoice['PaidAmount']) > 0 else 'received'
                odoo_invoice.write({
                    'ebiz_invoice_status': status,
                    'receipt_ref_num': invoice['RefNum'],
                    'is_payment_processed': True,
                })
                self.env['account.move.receipts'].create({
                    'invoice_id': odoo_invoice.id,
                    'name': self.env.user.currency_id.symbol + invoice['PaidAmount'][:-2] + ' Paid On ' +
                            invoice['PaymentRequestDateTime'].split('T')[0],
                    'ref_nums': invoice['RefNum'],
                    'model': str(self._inherit),
                })
                journal_id, ebiz_method = odoo_invoice._get_ebiz_journal_and_method()
                if not journal_id:
                    continue
                payment = self.env['account.payment'] \
                    .sudo().with_context(active_ids=odoo_invoice.ids, active_model='account.move',
                                         active_id=odoo_invoice.id) \
                    .create({
                        'journal_id': journal_id.id,
                        'payment_method_id': ebiz_method.payment_method_id.id,
                        'payment_method_line_id': ebiz_method.id,
                        'amount': float(invoice['PaidAmount']),
                        'token_type': None,
                        'partner_id': odoo_invoice.partner_id.id,
                        'transaction_ref': odoo_invoice.name or None,
                        'payment_type': 'inbound',
                        'memo': odoo_invoice._build_payment_memo(),
                    })
                payment.with_context({'pass_validation': True}).action_post()
                odoo_invoice.with_context({'payment_id': payment.id}).reconcile()
                odoo_invoice.sync_to_ebiz()
                odoo_invoice.write({'save_payment_link': False, 'ebiz_payment_link': 'applied',
                                    'request_amount': 0, 'last_request_amount': 0})
                if odoo_invoice['amount_residual'] <= 0:
                    super(AccountMoveInh, odoo_invoice).payment_action_capture()
                    odoo_invoice.mark_as_applied()
                else:
                    ebiz.client.service.MarkEbizWebFormPaymentAsApplied(**{
                        'securityToken': ebiz._generate_security_json(),
                        'paymentInternalId': odoo_invoice.payment_internal_id,
                    })
            except Exception:
                _logger.exception("Failed to apply web form payment for invoice %s", odoo_invoice.id)
                continue

    def _apply_quick_payments(self, ebiz, start, end):
        quick_payments = ebiz.client.service.GetPayments(**{
            'securityToken': ebiz._generate_security_json(),
            'fromDateTime': str(start.date()),
            'toDateTime': str(end.date()),
            'start': 0,
            'limit': 10000,
        })
        if not quick_payments:
            return
        for pay in quick_payments:
            try:
                if pay['InvoiceInternalId']:
                    is_odoo_invoice = self.env['account.move'].search(
                        [('ebiz_internal_id', '=', pay['InvoiceInternalId'])])
                    is_credit = self.env['account.payment'].search([('name', '=', pay['InvoiceNumber'])])
                    if is_odoo_invoice:
                        is_odoo_invoice.ebiz_create_payment_line(pay['PaidAmount'])
                        ebiz.client.service.MarkPaymentAsApplied(**{
                            'securityToken': ebiz._generate_security_json(),
                            'paymentInternalId': pay['PaymentInternalId'],
                            'invoiceNumber': pay['InvoiceNumber'],
                        })
                        self.env['account.move.receipts'].create({
                            'invoice_id': is_odoo_invoice.id,
                            'name': self.env.user.currency_id.symbol + pay['PaidAmount'][:-2] + ' Paid On ' +
                                    pay['DatePaid'].split('T')[0],
                            'ref_nums': pay['RefNum'],
                            'model': str(self._inherit),
                        })
                    if is_credit:
                        ebiz.client.service.MarkPaymentAsApplied(**{
                            'securityToken': ebiz._generate_security_json(),
                            'paymentInternalId': pay['PaymentInternalId'],
                            'invoiceNumber': pay['InvoiceNumber'],
                        })
                        is_credit.action_draft()
                        is_credit.cancel()
                else:
                    partner = self.env['res.partner'].search([('id', '=', pay['CustomerId'])])
                    if not (partner and pay['TypeId'] in ['QuickPay']):
                        continue
                    journal_id, ebiz_method = self._get_ebiz_journal_and_method(
                        company=partner.company_id or self.env.company)
                    if not journal_id:
                        continue
                    ebiz.client.service.MarkPaymentAsApplied(**{
                        'securityToken': ebiz._generate_security_json(),
                        'paymentInternalId': pay['PaymentInternalId'],
                        'invoiceNumber': pay['InvoiceNumber'] or '',
                    })
                    self.env['account.payment'].sudo().create({
                        'journal_id': journal_id.id,
                        'payment_method_id': ebiz_method.payment_method_id.id,
                        'payment_method_line_id': ebiz_method.id,
                        'partner_id': partner.id,
                        'payment_reference': pay['RefNum'],
                        'amount': pay['PaidAmount'],
                        'partner_type': 'customer',
                        'payment_type': 'inbound',
                        'transaction_ref': pay['InvoiceNumber'] or '',
                    }).action_post()
            except Exception:
                _logger.exception("Failed to apply quick payment ref %s", pay.get('RefNum'))
                continue

    def _apply_recurring_payments(self, ebiz, start, end):
        recurring_payments = ebiz.client.service.SearchRecurringPayments(**{
            'securityToken': ebiz._generate_security_json(),
            "fromDateTime": str(start.date()),
            "toDateTime": str(end.date()),
            "limit": 1000,
            "start": 0,
        })
        if not recurring_payments:
            return
        for r_pay in recurring_payments:
            try:
                partner = self.env['res.partner'].search([('id', '=', r_pay['CustomerId'])])
                if not partner:
                    continue
                journal_id, ebiz_method = self._get_ebiz_journal_and_method(
                    company=partner.company_id or self.env.company)
                if not journal_id:
                    continue
                ebiz.client.service.MarkRecurringPaymentAsApplied(**{
                    'securityToken': ebiz._generate_security_json(),
                    'paymentInternalId': r_pay['PaymentInternalId'],
                    'invoiceNumber': r_pay['InvoiceNumber'] or '',
                })
                self.env['account.payment'].sudo().create({
                    'journal_id': journal_id.id,
                    'payment_method_id': ebiz_method.payment_method_id.id,
                    'payment_method_line_id': ebiz_method.id,
                    'partner_id': partner.id,
                    'payment_reference': r_pay['RefNum'],
                    'amount': r_pay['PaidAmount'],
                    'partner_type': 'customer',
                    'payment_type': 'inbound',
                    'transaction_ref': r_pay['InvoiceNumber'] or '',
                }).action_post()
            except Exception:
                _logger.exception("Failed to apply recurring payment ref %s", r_pay.get('RefNum'))
                continue

    def received_apply_email_after_confirmation(self, invoice):
        try:
            odoo_invoice = self
            if odoo_invoice.state != 'posted':
                odoo_invoice.action_post()

            odoo_invoice.write({
                'ebiz_invoice_status': 'partially_received' if odoo_invoice['amount_residual'] - float(invoice['PaidAmount']) > 0 else 'received',
                'receipt_ref_num': invoice['RefNum'],
                'is_payment_processed': True,
            })

            self.env['account.move.receipts'].create({
                'invoice_id': odoo_invoice.id,
                'name': self.env.user.currency_id.symbol + invoice['PaidAmount'][:-2] + ' Paid On ' +
                        invoice['PaymentRequestDateTime'].split('T')[0],
                'ref_nums': invoice['RefNum'],
                'model': str(self._inherit),
            })
            journal_id, ebiz_method = self._get_ebiz_journal_and_method()
            if journal_id:
                memo = self._build_payment_memo()
                payment = self.env['account.payment'] \
                    .sudo().with_context(active_ids=odoo_invoice.ids, active_model='account.move',
                                  active_id=odoo_invoice.id) \
                    .create(
                    {'journal_id': journal_id.id,
                     'payment_method_id': ebiz_method.payment_method_id.id,
                     'payment_method_line_id': ebiz_method.id,
                     'amount': float(invoice['PaidAmount']),
                     'token_type': None,
                     'partner_id': self.partner_id.id,
                     'transaction_ref': self.name or None,
                     'payment_type': 'inbound',
                     'memo': memo
                     })
                payment.with_context({'pass_validation': True}).action_post()
                self.with_context({'payment_id': payment.id}).reconcile()
                odoo_invoice.sync_to_ebiz()
                odoo_invoice.save_payment_link = False
                if odoo_invoice['amount_residual'] <= 0:
                    res = super(AccountMoveInh, odoo_invoice).payment_action_capture()
                    odoo_invoice.mark_as_applied()
                    return res
                else:
                    ebiz = self._get_ebiz_client()
                    ebiz.client.service.MarkEbizWebFormPaymentAsApplied(**{
                        'securityToken': ebiz._generate_security_json(),
                        'paymentInternalId': odoo_invoice.payment_internal_id,
                    })
            else:
                raise UserError('EBizCharge Journal Not Found!')

        except Exception as e:
            raise UserError(e)

    def reconcile(self):
        for invoice_payment in self:
            payments = self.env['account.payment'].sudo().search(
                [('payment_reference', '=', invoice_payment.name), ('company_id', '=', invoice_payment.company_id.id)])
            if not payments and self.env.context.get('payment_id'):
                payments = self.env['account.payment'].sudo().browse(self.env.context.get('payment_id'))
            for payment in payments:
                if not payment.is_reconciled and payment.state == 'in_process':
                    payment.action_validate()
                if not payment.is_reconciled and payment.state == 'paid':
                    payment_ref = self.env['account.move.line'].search(
                        [('move_name', '=', payment.name), ('move_id.company_id', '=', invoice_payment.company_id.id)])
                    if payment_ref:
                        index = len(payment_ref) - 1
                        invoice_payment.js_assign_outstanding_line(payment_ref[index].id)

    def action_capture_reconcile(self, payments):
        for invoice_payment in self:
            for payment in payments:
                if not payment.is_reconciled and payment.state in  ('paid','in_process'):
                    payment_ref = self.env['account.move.line'].search(
                        [('move_name', '=', payment.display_name), ('move_id.company_id', '=', invoice_payment.company_id.id)])
                    if payment_ref:
                        index = len(payment_ref) - 1
                        invoice_payment.js_assign_outstanding_line(payment_ref[index].id)

    @api.model
    def _cron_refresh_pending_invoice_status(self):
        """Scheduled action: check EBizCharge for received payments on all pending email-pay invoices."""
        pending = self.search([
            '|',
            ('ebiz_invoice_status', '=', 'pending'),
            ('ebiz_payment_link', '=', 'pending'),
            ('email_received_payments', '=', False),
        ])
        if not pending:
            return

        start, end = self._get_ebiz_date_range()
        invoice_obj = self.env['account.move']

        for profile in pending.partner_id.ebiz_profile_id:
            try:
                ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=profile)
                received_payments = ebiz.client.service.SearchEbizWebFormReceivedPayments(**{
                    'securityToken': ebiz._generate_security_json(),
                    'fromPaymentRequestDateTime': str(start.date()),
                    'toPaymentRequestDateTime': str(end.date()),
                    'start': 0,
                    'limit': 10000,
                })
                if not received_payments:
                    continue
                for payment in received_payments:
                    odoo_invoice = self.search([
                        ('payment_internal_id', '=', payment['PaymentInternalId']),
                        '|',
                        ('ebiz_invoice_status', '=', 'pending'),
                        ('ebiz_payment_link', '=', 'pending'),
                    ])
                    if not odoo_invoice:
                        continue
                    if odoo_invoice.save_payment_link:
                        odoo_invoice.ebiz_payment_link = 'received'
                    else:
                        odoo_invoice.email_received_payments = True
            except Exception:
                _logger.exception("Failed to refresh pending invoice status for profile %s", profile.id)

    def delete_ebiz_invoice(self):
        try:
            ebiz = self._get_ebiz_client()

            received_payments = ebiz.client.service.DeleteEbizWebFormPayment(**{
                'securityToken': ebiz._generate_security_json(),
                'paymentInternalId': self.payment_internal_id,
            })

            if received_payments.Status == 'Success' or self.save_payment_link:
                self.write({
                    'ebiz_invoice_status': 'delete',
                    'email_received_payments': False,
                    'save_payment_link': False,
                    'odoo_payment_link': False,
                    'request_amount': self.request_amount - self.last_request_amount,
                })

                return message_wizard('Email pay request has been successfully canceled!')

        except Exception as e:
            raise UserError(e)

    def mark_as_applied(self):
        try:
            ebiz = self._get_ebiz_client()
            received_payments = ebiz.client.service.MarkEbizWebFormPaymentAsApplied(**{
                'securityToken': ebiz._generate_security_json(),
                'paymentInternalId': self.payment_internal_id,

            })
            if received_payments.Status == 'Success':
                self.ebiz_invoice_status = 'applied'
                self.is_payment_processed = True
        except Exception as e:
            raise UserError(e)

    def show_pending_ebiz_email(self):
        ebiz = self._get_ebiz_client()
        start, end = self._get_ebiz_date_range()

        received_payments = ebiz.client.service.SearchEbizWebFormReceivedPayments(**{
            'securityToken': ebiz._generate_security_json(),
            'fromPaymentRequestDateTime': str(start.date()),
            'toPaymentRequestDateTime': str(end.date()),
            'start': 0,
            'limit': 10000,
        })
        if received_payments:
            for invoice in received_payments:
                odoo_invoice = self.env['account.move'].search(
                    [('payment_internal_id', '=', invoice['PaymentInternalId']),
                     ('ebiz_invoice_status', '=', 'pending')])

                if odoo_invoice and odoo_invoice.id == self.id:
                    self.email_received_payments = True
                    text = f"There is an email payment of {float(invoice['PaidAmount'])} received on this {self.name}.\nDo you want to apply?"
                    wizard = self.env['wizard.receive.email.pay'].create({"record_id": self.id,
                                                                          "odoo_invoice": odoo_invoice.id,
                                                                          "text": text})
                    action = self.env.ref('payment_ebizcharge_crm.wizard_received_email_pay').read()[0]
                    action['res_id'] = wizard.id
                    action['context'] = dict(
                        invoice=invoice,
                    )
                    return action
                else:
                    continue

        start, end = self._get_ebiz_date_range(7)
        params = {
            'securityToken': ebiz._generate_security_json(),
            'fromPaymentRequestDateTime': str(start.date()),
            'toPaymentRequestDateTime': str(end.date()),
            "filters": {
                "SearchFilter": [{
                    'FieldName': 'InvoiceNumber',
                    'ComparisonOperator': 'eq',
                    'FieldValue': str(self.name)
                }]
            },
            "limit": 1000,
            "start": 0,
        }
        payments = ebiz.client.service.SearchEbizWebFormPendingPayments(**params)
        payment_lines = []
        if not payments:
            return message_wizard('Cannot find any pending payments')
        for payment in payments:
            payment_line = {
                "payment_type": payment['PaymentType'],
                "payment_internal_id": payment['PaymentInternalId'],
                "customer_id": payment['CustomerId'],
                "invoice_number": payment['InvoiceNumber'],
                "invoice_internal_id": payment['InvoiceInternalId'],
                "invoice_date": payment['InvoiceDate'],
                "invoice_due_date": payment['InvoiceDueDate'],
                "po_num": payment['PoNum'],
                "currency_id": self.env.user.currency_id.id,
                "invoice_amount": payment['InvoiceAmount'],
                "amount_due": payment['AmountDue'],
                "email_amount": payment['AmountDue'],
                "auth_code": payment['AuthCode'],
                "ref_num": payment['RefNum'],
                "payment_method": payment['PaymentMethod'],
                "date_paid": datetime.strptime(payment['PaymentRequestDateTime'], '%Y-%m-%dT%H:%M:%S'),
                "paid_amount": payment['PaidAmount'],
                "type_id": payment['TypeId'],
                "email_id": payment['CustomerEmailAddress'],
            }
            payment_lines.append(fields.Command.create(payment_line))
        wiz = self.env['ebiz.pending.payment'].create({})
        wiz.payment_lines = payment_lines
        action = self.env.ref('payment_ebizcharge_crm.action_ebiz_pending_payments_form').read()[0]
        action['res_id'] = wiz.id
        return action

    def _ebiz_check_invoice_update(self, values):
        update_fields = {"partner_id", "name", "invoice_date", "amount_total", "invoice_date_due",
                         "currency_id", "amount_tax", "user_id", "invoice_line_ids", "amount_residual",
                         "ebiz_invoice_status"}
        return any(f in values for f in update_fields)

    def email_receipt_ebiz(self):
        try:
            instance = self._get_ebiz_instance()
            email_obj = self.env['email.receipt']
            ebiz = self._get_ebiz_client()
            receipts = ebiz.client.service.GetEmailTemplates(**{
                'securityToken': ebiz._generate_security_json(),
            })
            if receipts and instance:
                for template in receipts:
                    odoo_temp = email_obj.search(
                        [('receipt_id', '=', template['TemplateInternalId']), ('instance_id', '=', instance.id)])
                    if not odoo_temp:
                        if template['TemplateTypeId'] in ('TransactionReceiptMerchant', 'TransactionReceiptCustomer'):
                            email_obj.create({
                                'name': template['TemplateName'],
                                'receipt_subject': template['TemplateSubject'],
                                'receipt_id': template['TemplateInternalId'],
                                'target': template['TemplateDescription'],
                                'content_type': template['TemplateTypeId'],
                                'instance_id': instance.id,
                            })
            return {'type': 'ir.actions.act_window',
                    'name': _('Email Receipt'),
                    'res_model': 'wizard.email.receipts',
                    'target': 'new',
                    'view_mode': 'form',
                    'view_type': 'form',
                    'context': {
                        'default_partner_ids': [fields.Command.set([self.partner_id.id])],
                        'default_record_id': self.id,
                        'default_ebiz_profile_id': self.partner_id.ebiz_profile_id.id,
                        'default_email_transaction_id': self.receipt_ref_num,
                        'default_model_name': str(self._inherit),
                        'default_email_customer': str(self.partner_id.email if self.partner_id.email else ''),
                        'selection_check': 1,
                    }}
        except Exception as e:
            raise UserError(e)

    def _has_to_be_paid(self):
        """
            Default method is inherited to hide pay button for authorised invoices.
        """
        self.ensure_one()
        transactions = self.transaction_ids.filtered(lambda tx: tx.state in ('authorized', 'done'))
        return bool(
            (
                    self.amount_residual
                    # FIXME someplace we check amount_residual and some other amount_paid < amount_total
                    # what is the correct heuristic to check ?
                    or not transactions
            )
            and self.state == 'posted'
            and transactions.filtered(lambda tx: tx.state not in ('authorized', 'done')) if self.payment_state in (
                'paid') else True and self.payment_state in ('not_paid', 'partial')
                             and self.amount_total and self.move_type == 'out_invoice')

    def view_logs(self):
        return {
            'name': (_('Invoices Logs')),
            'view_type': 'form',
            'res_model': 'invoices.logs',
            'target': 'new',
            'view_id': False,
            'view_mode': 'list,pivot,form',
            'type': 'ir.actions.act_window',
        }

    def request_email_invoice_bulk(self):
        try:
            instances = self.env['ebizcharge.instance.config'].search([('is_valid_credential', '=', True)])
            ebiz_obj = self.env['ebiz.charge.api']
            ebiz_templates = self.env['email.templates']
            for instance in instances:
                ebiz = ebiz_obj.get_ebiz_charge_obj(instance=instance)
                templates = ebiz.client.service.GetEmailTemplates(**{
                    'securityToken': ebiz._generate_security_json(),
                })
                if templates:
                    for template in templates:
                        odoo_temp = ebiz_templates.search(
                            [('template_id', '=', template['TemplateInternalId']), ('instance_id', '=', instance.id)])
                        if not odoo_temp:
                            ebiz_templates.create({
                                'name': template['TemplateName'],
                                'template_id': template['TemplateInternalId'],
                                'template_subject': template['TemplateSubject'],
                                'template_description': template['TemplateDescription'],
                                'template_type_id': template['TemplateTypeId'],
                                'instance_id': instance.id,
                            })
                        else:
                            odoo_temp.write({
                                'template_subject': template['TemplateSubject'],
                            })

            invoice_ids = [ids.id for ids in self if ids.payment_state != 'paid']
            if not invoice_ids:
                raise UserError('The Selected invoices are already Paid!')

            return {'type': 'ir.actions.act_window',
                    'name': _('Email Pay Request'),
                    'res_model': 'multiple.email.invoice.payments',
                    'target': 'new',
                    'view_mode': 'form',
                    'view_type': 'form',
                    'context': {
                        'default_invoice_ids': [fields.Command.set(invoice_ids)],
                        'selection_check': 1,
                    },
                    }

        except Exception as e:
            raise UserError(e)

    def button_draft(self):
        ret = super(AccountMoveInh, self).button_draft()
        for rec in self:
            if (rec.move_type == "out_refund" or rec.move_type == "out_invoice") and rec.ebiz_internal_id \
                    and rec.payment_state != 'paid' and not rec.done_transaction_ids:
                ebiz = rec._get_ebiz_client()
                ebiz.client.service.UpdateInvoice(**{
                    'securityToken': ebiz._generate_security_json(),
                    'invoice': {
                        "AmountDue": 0,
                        "InvoiceAmount": 0,
                        "NotifyCustomer": False,
                    },
                    'customerId': rec.partner_id.id,
                    'invoiceNumber': rec.name,
                    'invoiceInternalId': rec.ebiz_internal_id
                })
        return ret

    def js_assign_outstanding_line(self, line_id):
        instances = self.env['ebizcharge.instance.config'].search(
            [('is_valid_credential', '=', True)])
        if instances and self.move_type in ['out_refund', 'out_invoice']:
            self.ensure_one()
            lines = self.env['account.move.line'].browse(line_id)
            ebiz = self._get_ebiz_client()
            from_date = datetime.strftime((self.create_date - timedelta(days=1)), '%Y-%m-%dT%H:%M:%S')
            to_date = datetime.strftime((datetime.now() + timedelta(days=1)), '%Y-%m-%dT%H:%M:%S')
            params = {
                'securityToken': ebiz._generate_security_json(),
                "fromDateTime": from_date,
                "toDateTime": to_date,
                "customerId": self.partner_id.id,
                "limit": 1000,
                "start": 0,
            }
            payments = ebiz.client.service.GetPayments(**params)
            payments = list(filter(lambda x: x['InvoiceNumber'] == lines.payment_id.name, payments or []))
            if payments:
                for payment in payments:
                    resp = ebiz.client.service.MarkPaymentAsApplied(**{
                        'securityToken': ebiz._generate_security_json(),
                        'paymentInternalId': payment['PaymentInternalId'],
                        'invoiceNumber': lines.payment_id.name
                    })
                payment_id = lines.payment_id
                payment_id.action_draft()
                payment_id.action_cancel()
            else:
                result = super(AccountMoveInh, self).js_assign_outstanding_line(line_id)
                self.sync_to_ebiz()
                return result
        else:
            return super(AccountMoveInh, self).js_assign_outstanding_line(line_id)

    def action_generate_odoo_payment_link(self):
        if self.email_received_payments:
            raise UserError('Invoice is already paid. You cannot generate a payment link!')
        instance = self._get_ebiz_instance()

        if self.save_payment_link and self.payment_internal_id:
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
            ebiz.client.service.DeleteEbizWebFormPayment(**{
                'securityToken': ebiz._generate_security_json(),
                'paymentInternalId': self.payment_internal_id,
            })

        if self.ebiz_invoice_status in ['pending']:
            if self and self.save_payment_link and self.is_email_request:
                message_log = 'Email Pay Request sent to: ' + str(self.email_for_pending) + '  has been invalidated'
                self.message_post(body=message_log)
                self.save_payment_link = False
        elif self and self.save_payment_link:
            self.message_post(
                body=Markup(
                    'EBizCharge Payment Link invalidated: <a href="%s" target="_blank">%s</a>' % (
                        self.save_payment_link, self.save_payment_link)
                ),
                message_type="comment",
            )
            self.save_payment_link = False

        self.odoo_payment_link = True
        return {
            'type': 'ir.actions.act_window',
            'name': 'Generate a Payment Link',
            'view_id': self.env.ref('payment.payment_link_wizard_view_form', False).id,
            'target': 'new',
            'res_model': 'payment.link.wizard',
            'view_mode': 'form',
        }

    @api.model
    def get_views(self, views, options=None):
        res = super().get_views(views, options)
        action_id = self.env.ref('account_payment.action_invoice_order_generate_link').id or False
        if action_id:
            for view in res['views'].values():
                if 'toolbar' in view and 'action' in view['toolbar']:
                    for button in view['toolbar']['action']:
                        if action_id and button['id'] == action_id:
                            view['toolbar']['action'].remove(button)
        return res


    def generate_payment_link(self):
        try:
            if len(self) == 0:
                raise UserError('Please select a record first!')
            if len(self.partner_id.ebiz_profile_id)>1:
                raise UserError('Filter the Invoices for a specific unique merchant account. Selection of Invoices for more than one merchant account is not allowed.')

            profile = False
            payment_lines = []

            if self:
                odoo_pay_link = False
                ebiz_pay_link = False
                for inv in self:
                    if inv.odoo_payment_link:
                        odoo_pay_link = True
                    if inv.save_payment_link:
                        ebiz_pay_link = True
                if odoo_pay_link:
                    text = f"This document has a pending payment link. Proceeding may increase the risk of double payments. Do you want to continue?"
                    wizard = self.env['wizard.receive.email.payment.link'].create({
                        "is_pay_link": True,
                        "invoice_ids": [fields.Command.set(self.ids)],
                        "text": text,
                    })
                    action = self.env.ref('payment_ebizcharge_crm.wizard_received_email_pay_payment_link').read()[0]
                    action['res_id'] = wizard.id
                    return action

                elif ebiz_pay_link:
                    text = f"This document has an existing payment link. Proceeding will invalidate the existing link. Do you want to continue?"
                    wizard = self.env['wizard.receive.email.payment.link'].create({
                        "is_pay_link": True,
                        "invoice_ids": [fields.Command.set(self.ids)],
                        "text": text,
                    })
                    action = self.env.ref('payment_ebizcharge_crm.wizard_received_email_pay_payment_link').read()[0]
                    action['res_id'] = wizard.id
                    return action
                else:
                    for inv in self:
                        if inv.move_type != 'out_invoice':
                            raise UserError(
                                'Generating an EBizCharge payment link is only available for invoice payments.')
                        if inv and inv.payment_state not in ("paid", "in_payment"):
                            payment_line = {
                                "invoice_id": inv.id,
                                "name": inv.name,
                                "customer_name": inv.partner_id.id,
                                "amount_due": inv.amount_residual_signed,
                                "amount_residual_signed": inv.amount_residual_signed,
                                "amount_total_signed": inv.amount_total,
                                "request_amount": inv.amount_residual_signed,
                                "odoo_payment_link": inv.odoo_payment_link,
                                "currency_id": self.env.user.currency_id.id,
                                "email_id": inv.partner_id.email,
                                "ebiz_profile_id": inv.partner_id.ebiz_profile_id.id,
                            }
                            payment_lines.append(fields.Command.create(payment_line))
                        profile = inv.partner_id.ebiz_profile_id.id
                    wiz = self.env['wizard.ebiz.generate.link.payment.bulk'].with_context(
                        profile=profile).create(
                        {'payment_lines': payment_lines,
                         'invoice_link': True,
                         'ebiz_profile_id': profile})
                    action = self.env.ref('payment_ebizcharge_crm.wizard_generate_link_form_views_action').read()[0]
                    action['res_id'] = wiz.id
                    action['context'] = self.env.context
                    return action
        except Exception as e:
            raise ValidationError(e)






    def action_view_payment_transactions(self):
        action = self.env['ir.actions.act_window']._for_xml_id('payment.action_payment_transaction')
        transactions = self.transaction_ids
        count = len(self.transaction_ids.ids)
        if self.transaction_ids.sale_order_ids:
            other = self.transaction_ids.sale_order_ids.done_transaction_ids.filtered(lambda i:i.id not in self.transaction_ids.ids)
            count = len(transactions.ids) + len(other.ids)
            transactions += other
        if count == 1:
            action['view_mode'] = 'form'
            action['res_id'] = self.transaction_ids.id
            action['views'] = []
        else:
            action['domain'] = [('id', 'in', transactions.ids)]

        return action


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def action_register_payment(self, ctx=None):
        ''' Open the account.payment.register wizard to pay the selected journal items.
        :return: An action opening the account.payment.register wizard.
        '''
        ret = super(AccountMoveLine, self).action_register_payment()
        check = any(inv_line.move_id.save_payment_link for inv_line in self)
        ret['context'].update({
            'default_is_pay_link': check
        })
        if 'active_id' not in self.env.context:
            ret['context'].update({
                'active_id': self.move_id.id if len(self.move_id) == 1 else False,
                'main_model': 'account.move',
            })
        return ret

    def js_update_enable_sur(self, **kwargs):
        if self.exists():
            self.move_id.js_update_enable_sur(**kwargs)


class AccountReceipts(models.Model):
    _name = 'account.move.receipts'
    _description = "Account Move Receipts"

    invoice_id = fields.Char(string='Invoice ID')
    name = fields.Char(string='Name')
    ref_nums = fields.Char(string='Ref Num')
    model = fields.Char(string='Model Name')





