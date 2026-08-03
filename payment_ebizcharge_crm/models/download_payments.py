from odoo import fields, models, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import datetime, timedelta
import logging
from ..models.ebiz_charge import message_wizard

_logger = logging.getLogger(__name__)


class DownloadEBizPayment(models.TransientModel):
    _name = 'ebiz.download.payments'
    _description = "EBiz Download Payments"

    def get_default_from_date(self):
        return self.env['ebizcharge.instance.config'].get_document_download_start_date()

    def get_default_to_date(self):
        today = datetime.now()
        end = today + timedelta(days=1)
        return end.date()

    def domain_users(self):
        domain = []
        if 'active_id' in self.env.context and self.env.context.get('active_id') is not None:
            rec = self.env['ebiz.download.payments'].browse([self.env.context.get('active_id')])
            domain.append(('partner_id.ebiz_profile_id', '=', rec.ebiz_profile_id.id))
        else:
            today = datetime.now()
            end = today + timedelta(days=1)

            start = self.env['ebizcharge.instance.config'].get_document_download_start_date()
            dt_start = datetime.combine(start, datetime.min.time())

            domain.append(('last_sync_date', '>=', dt_start))
            domain.append(('last_sync_date', '<=', end))
            default_instance = self.env['ebizcharge.instance.config'].search(
                [('is_valid_credential', '=', True), ('is_default', '=', True), ('is_active', '=', True)], limit=1)
            if default_instance:
                domain.append(('partner_id.ebiz_profile_id', '=', default_instance.id))
        return domain

    def get_default_company(self):
        return self.env.context.get('allowed_company_ids')

    def _default_instance_id(self):
        return self.env['ebizcharge.instance.config']._default_instance_id()

    from_date = fields.Date("From Date", required=True, default=get_default_from_date)
    is_adjustment_field = fields.Char(string='Adjustment')
    to_date = fields.Date("To Date", required=True, default=get_default_to_date)
    payment_lines = fields.One2many('ebiz.payment.lines', 'wiz_id')
    name = fields.Char(string='Download Received Payments', default=lambda self: _('Download Received Payments'))
    transaction_log_lines = fields.Many2many('sync.logs', copy=True, domain=lambda self: self.domain_users())
    payment_category = fields.Selection([
                                   ('all', 'All'), 
                                   ('portal_mobile', 'Portal and Mobile'),
                                         ('email_pay', 'Payment Links'),
                                         ('fixed_amount', 'Fixed Amount Auto Payments')], string='Payment Category',
                                        default='portal_mobile')
    is_download_pressed = fields.Boolean()
    is_download_pressed_fixed_auto_amount = fields.Boolean()
    company_ids = fields.Many2many('res.company', compute='compute_company', default=get_default_company)
    ebiz_profile_id = fields.Many2one('ebizcharge.instance.config', string='EBizCharge Profile',
                                      default=_default_instance_id)

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = 'Download Received Payments'

    def get_recurring_payments(self, start, end, ebiz):
        params = {
            'securityToken': ebiz._generate_security_json(),
            "fromDateTime": str(start),
            "toDateTime": str(end),
            "limit": 1000,
            "start": 0,
        }
        payments = ebiz.client.service.SearchRecurringPayments(**params)
        payment_lines = [fields.Command.clear()]

        if payments:
            for payment in payments:
                if payment['CustomerId'] != 'False' and payment['CustomerId'].isnumeric():
                    odoo_customer = self.env['res.partner'].browse(int(payment['CustomerId'])).exists()
                    if odoo_customer:
                        get_transaction = ebiz.client.service.GetTransactionDetails(
                            **{'securityToken': ebiz._generate_security_json(),
                               'transactionRefNum': payment['RefNum']})
                        payment_line = self.get_payment_line(payment, odoo_customer)
                        payment_line['type_id'] = "Fixed Amount Auto Payments"
                        payment_line['source'] = get_transaction['Source']
                        payment_lines += [fields.Command.create(payment_line)]
        return payment_lines

    def get_payments(self, start, end, ebiz):
        params = {
            'securityToken': ebiz._generate_security_json(),
            "fromDateTime": str(start),
            "toDateTime": str(end),
            "limit": 1000,
            "start": 0,
        }
        payments = ebiz.client.service.GetPayments(**params)
        payment_lines = [fields.Command.clear()]

        if payments:
            for payment in payments:
                if payment['CustomerId'] != 'False' and payment['CustomerId'].isnumeric():
                    odoo_customer = self.env['res.partner'].browse(int(payment['CustomerId'])).exists()
                    if odoo_customer:
                        payment_line = self.get_payment_line(payment, odoo_customer)
                        payment_line['type_id'] = 'Credit Note Payment' if payment[
                                                                               'TypeId'] == 'InvCredit' else self.get_payment_type(
                            payment['PaymentType'])
                        payment_lines += [fields.Command.create(payment_line)]
        return payment_lines

    def get_received_email_payments(self, start, end, ebiz):
        params = {
            'securityToken': ebiz._generate_security_json(),
            "fromPaymentRequestDateTime": str(start),
            "toPaymentRequestDateTime": str(end),
            "filters": {'SearchFilter': []},
            "limit": 1000,
            "start": 0,
        }
        payments = ebiz.client.service.SearchEbizWebFormReceivedPayments(**params)
        payment_lines = [fields.Command.clear()]

        if payments:
            for payment in payments:
                if payment['InvoiceNumber'] in ['PM', "Token"]: continue
                if payment['CustomerId'] != 'False' and payment['CustomerId'].isnumeric():
                    try:
                        odoo_customer = self.env['res.partner'].browse(int(payment['CustomerId'])).exists()
                    except Exception:
                        _logger.exception("Failed to browse partner %s", payment['CustomerId'])
                        continue
                    if odoo_customer:
                        type_id = 'Email Pay' if payment['TypeId'] == 'EmailForm' else payment['TypeId']
                        source = 'Email Pay' if payment['PaymentSourceId'].strip() == 'Odoo CRM' else payment['PaymentSourceId'] or "N/A"
                        should_add = True
                        if payment['InvoiceNumber']:
                            name = payment['InvoiceNumber'].split(' ', 1)[0]
                            invoice = self.env['account.move'].search([('name', '=', name)])
                            sale = self.env['sale.order'].search([('name', '=', name)])
                            should_add = bool(invoice or sale)
                        if should_add:
                            payment_line = self.get_payment_line(payment, odoo_customer)
                            payment_line['type_id'] = type_id
                            payment_line['is_email_payment'] = True
                            payment_line['source'] = source
                            payment_lines += [fields.Command.create(payment_line)]
        return payment_lines

    def get_payment_line(self, payment, partner):
        currency_id = partner.property_product_pricelist.currency_id.id

        def ref_date(date):
            if not date:
                return date
            if '-' in date:
                rf_date = date.split('-')
            else:
                rf_date = date.split('/')
            return f"{rf_date[1]}/{rf_date[2]}/{rf_date[0]}"
        sale = False
        is_save_link = False
        if payment['InvoiceNumber']:
            sale = self.env['sale.order'].search([('name', '=', payment['InvoiceNumber'].split(' ', 1)[0])])
        if sale and sale.invoice_status not in ('no','to invoice') and not sale.partner_id.ebiz_profile_id.apply_sale_pay_inv:
            is_save_link = True
        payment_method = payment['PaymentMethod'] or 'ACH'
        return {
            "payment_type": payment['PaymentType'],
            "payment_internal_id": payment['PaymentInternalId'],
            "customer_id": str(payment['CustomerId']),
            "partner_id": int(payment['CustomerId']),
            "invoice_number": payment['InvoiceNumber'],
            "invoice_number_op": payment['InvoiceNumber'],
            "invoice_internal_id": payment['InvoiceInternalId'],
            "invoice_date": ref_date(payment['InvoiceDate']),
            "invoice_due_date": ref_date(payment['InvoiceDueDate']),
            "po_num": payment['PoNum'],
            "invoice_amount": float(payment['InvoiceAmount'] or "0"),
            "currency_id": currency_id,
            "amount_due": float(payment['AmountDue'] or "0"),
            "auth_code": payment['AuthCode'],
            "ref_num": payment['RefNum'],
            "is_save_link": is_save_link,
            "payment_method": f"{payment_method} ending in {payment['Last4']}",
            "date_paid": ref_date(payment['DatePaid'].split('T')[0]),
            "paid_amount": float(payment['PaidAmount'] or "0"),
            "paid_amount_op": payment['PaidAmount'],
            "source": payment['PaymentSourceId'],
        }

    _PAYMENT_TYPE_MAP = {
        'RecurringFullBalanceInvoicePayment': 'Statement Auto Payment',
        'InvoicePayment': 'Invoice Payments',
        'QuickPay': 'Quick Payment',
        'InvCredit': 'Credit',
    }

    def get_payment_type(self, type):
        return self._PAYMENT_TYPE_MAP.get(type, '')

    @api.depends('ebiz_profile_id')
    def compute_company(self):
        self.company_ids = self.env.context.get('allowed_company_ids')

    @api.model_create_multi
    def create(self, values):
        for val in values:
            if 'transaction_log_lines' in val:
                val['transaction_log_lines'] = None
        res = super(DownloadEBizPayment, self).create(values)
        return res

    def action_open_download_payments(self):
        profile_obj = self.env['ebizcharge.instance.config']
        profile = int(profile_obj.get_upload_instance(active_model='ebiz.download.payments', active_id=self))
        record = self
        if profile:
            ebiz_profile_id = self.env['ebizcharge.instance.config'].browse(int(profile))
            record = self.env['ebiz.download.payments'].create({'ebiz_profile_id': profile,
                                                                 'from_date': ebiz_profile_id._default_get_start(),
                                                                 'to_date': ebiz_profile_id._default_get_end_date()})
            record.regenerate_line_ids()
        return {
            "name": _("Download Received Payments"),
            "type": "ir.actions.act_window",
            "res_model": "ebiz.download.payments",
            "res_id": record.id,
            'view_id': self.env.ref('payment_ebizcharge_crm.view_ebiz_download_payments_form_v2', False).id,
            "view_mode": "form",
            "target": "inline",
        }

    def set_merchant_initial_values(self):
        profile_obj = self.env['ebizcharge.instance.config']
        profile = int(profile_obj.get_upload_instance(active_model='ebiz.download.payments', active_id=self))
        if profile:
            self.ebiz_profile_id = profile
            self.from_date = self.ebiz_profile_id._default_get_start()
            self.to_date = self.ebiz_profile_id._default_get_end_date()

    def regenerate_line_ids(self):
        if not self.ebiz_profile_id:
            self.set_merchant_initial_values()
        self.compute_payment_lines()
        self._create_logs_lines()

    def action_generate_line_ids(self):
        if not self.ebiz_profile_id:
            self.set_merchant_initial_values()
        self._create_logs_lines()
        return self._validate_and_create_received_payments()

    def _validate_and_create_received_payments(self):
        self.is_download_pressed_fixed_auto_amount = False
        if not self.payment_category:
            raise ValidationError('Please select a Payment Category before refreshing the table.')
        if self.payment_category == 'fixed_amount':
            self.is_download_pressed_fixed_auto_amount = True
        if self.from_date and self.to_date:
            if self.from_date >= self.to_date:
                message = 'From Date should be lower than the To date!'
                return message_wizard(message, 'Invalid Date')
        if self.payment_category == 'all':
            wizard = self.env['message.confirm.wizard'].create({"wizard_id": self.id,
                                                                "text": 'Downloading all payment types at once may take several minutes to load. Would you like to continue?', })

            action = self.env.ref('payment_ebizcharge_crm.action_message_confirm_wizard_form').read()[0]
            action['res_id'] = wizard.id
            return action
        self.compute_payment_lines()

    def _create_logs_lines(self):
        if not self or not self.from_date or not self.to_date:
            return
        odoo_logs = self.env['sync.logs'].search([]).filtered(
            lambda i: datetime.strptime(i.date_paid, '%m/%d/%Y').date() >= self.from_date and datetime.strptime(
                i.date_paid, '%m/%d/%Y').date() <= self.to_date)
        self.transaction_log_lines = [fields.Command.set(odoo_logs.ids)]

    _CATEGORY_METHODS = {
        'portal_mobile': ['get_payments'],
        'email_pay': ['get_received_email_payments'],
        'fixed_amount': ['get_recurring_payments'],
        'all': ['get_payments', 'get_received_email_payments', 'get_recurring_payments'],
    }

    def compute_payment_lines(self):
        if self.ebiz_profile_id:
            payments = []
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=self.ebiz_profile_id)
            for method_name in self._CATEGORY_METHODS.get(self.payment_category, []):
                payments += getattr(self, method_name)(self.from_date, self.to_date, ebiz)
            self.payment_lines = payments



class EBizPaymentLines(models.TransientModel):
    _name = 'ebiz.payment.lines'
    _description = "EBiz Payment Lines"

    wiz_id = fields.Many2one('ebiz.download.payments')
    check_box = fields.Boolean('Select')
    payment_internal_id = fields.Char('Payment Internal Id')
    partner_id = fields.Many2one('res.partner', 'Customer')
    customer_id = fields.Char('Customer ID')
    invoice_number = fields.Char('Invoice Number')
    invoice_number_op = fields.Char('Invoice Number #')
    invoice_internal_id = fields.Char('Invoice Internal Id')
    invoice_date = fields.Char('Invoice Date')
    invoice_due_date = fields.Char('Invoice Due Date')
    po_num = fields.Char('Po Num')
    so_num = fields.Char('So Num')
    invoice_amount = fields.Float('Invoice Total')
    amount_due = fields.Float('Balance Remaining')
    currency_id = fields.Many2one('res.currency')
    currency = fields.Char(string="Currency Name")
    auth_code = fields.Char('Auth Code')
    ref_num = fields.Char('Reference Number')
    payment_method = fields.Char('Payment Method')
    date_paid = fields.Char('Date Paid')
    paid_amount = fields.Float('Amount Paid')
    paid_amount_op = fields.Char('Amount Paid op')
    type_id = fields.Char('Type')
    payment_type = fields.Char('Payment Type')
    source = fields.Char('Source', default="Odoo")
    is_save_link = fields.Boolean(string="Save Link")
    is_payment_on_account = fields.Boolean(string="Is Payment on Account", help='If payment on account is set, It will create payment on customer account.')
    is_email_payment = fields.Boolean('Is Email Pay', default=False)

    def action_payment_import_into_odoo(self):
        if any(line.is_save_link for line in self):
            need_payment_on_account_ids = [line.id for line in self if line.is_save_link]
            text = "One or more sales orders have been converted to an invoice. Do you want to apply the payment(s) as payment on account?"
            wizard = self.env['message.confirm.wizard'].with_context({
                'line_ids': self.ids,
                'line_model': 'ebiz.payment.lines',
                'need_payment_on_account_ids': need_payment_on_account_ids
            }).create({"wizard_id": self.wiz_id.id, "text": text, "is_sale": True })
            action = self.env.ref('payment_ebizcharge_crm.action_message_confirm_wizard_form').read()[0]
            action['res_id'] = wizard.id
            action['context'] = dict(self.env.context)
            return action
        result = self.mark_as_applied()
        return result

    def payment_applied_for_invoice(self, ebiz, invoice_id):
        if not self.is_email_payment:
            resp = ebiz.client.service.MarkPaymentAsApplied(**{
                'securityToken': ebiz._generate_security_json(),
                'paymentInternalId': self.payment_internal_id,
                'invoiceNumber': self.invoice_number,
            })
        else:
            resp = ebiz.client.service.MarkEbizWebFormPaymentAsApplied(**{
                'securityToken': ebiz._generate_security_json(),
                'paymentInternalId': self.payment_internal_id,
            })
        if resp['Status'] == 'Success':
            invoice_id.ebiz_create_payment_line(self.paid_amount_op, self.payment_method)
        return resp

    def _prepare_payment_transaction_values(self, payment_acq, ebiz_method_tran, partner, sale, payment):
        return {
            'provider_id': payment_acq.sudo().id,
            'payment_method_id': ebiz_method_tran.id,
            'provider_reference': self.ref_num,
            'reference': self.env['payment.transaction']._compute_reference(payment_acq.code, prefix=sale.name),
            'amount': self.paid_amount,
            'currency_id': payment_acq.company_id.currency_id.id,
            'partner_id': partner.id,
            'token_id': False,
            'operation': 'offline',
            'sale_order_ids': [sale.id],
            'payment_id': payment.id if payment else False,
        }

    def _prepare_account_payment_values(self, payment_acq, ebiz_method, partner, memo):
        return {
            'journal_id': payment_acq.journal_id.id,
            'payment_method_id': ebiz_method.payment_method_id.id,
            'payment_method_line_id': ebiz_method.id,
            'partner_id': partner.id,
            'transaction_ref': self.ref_num,
            'amount': self.paid_amount,
            'partner_type': 'customer',
            'payment_type': 'inbound',
            'payment_reference': self.invoice_number_op if self.invoice_number_op else '',
            'memo': memo,
        }

    def create_payment_on_account(self, partner):
        payment_acq = self.env['payment.provider'].search(
            [('company_id', '=',
              partner.company_id.id if partner.company_id else self.env.company.id),
             ('code', '=', 'ebizcharge')])
        ebiz_method = self.env['account.payment.method.line'].search(
            [('journal_id', '=', payment_acq.journal_id.id),
             ('payment_method_id.code', '=', 'ebizcharge')], limit=1)
        payment = self.env['account.payment'].sudo().create(self._prepare_account_payment_values(payment_acq, ebiz_method, partner, ''))
        payment.action_post()

    def payment_applied_for_sale(self, ebiz, sale, partner):
        resp = False
        if sale and self.is_payment_on_account:
            resp = ebiz.client.service.MarkEbizWebFormPaymentAsApplied(**{
                'securityToken': ebiz._generate_security_json(),
                'paymentInternalId': self.payment_internal_id,
            })
            if resp and resp['Status'] == 'Success':
                self.create_payment_on_account(partner)
        elif sale and self.type_id == 'PayLinkOnly':
            resp = ebiz.client.service.MarkEbizWebFormPaymentAsApplied(**{
                'securityToken': ebiz._generate_security_json(),
                'paymentInternalId': self.payment_internal_id,
            })
            if resp and resp['Status'] == 'Success':
                payment_acq = self.env['payment.provider'].search(
                    [('company_id', '=',
                      partner.company_id.id if partner.company_id else self.env.company.id),
                     ('code', '=', 'ebizcharge')], limit=1)
                ebiz_method_tran = self.env['payment.method'].search(
                    [('code', '=', 'ebizcharge')], limit=1)
                ebiz_method = self.env['account.payment.method.line'].search(
                    [('journal_id', '=', payment_acq.journal_id.id),
                     ('payment_method_id.code', '=', 'ebizcharge')], limit=1)
                payment = False
                transactions = ebiz.client.service.GetTransactionDetails(
                    **{'securityToken': ebiz._generate_security_json(),
                       'transactionRefNum': self.ref_num})
                if transactions['TransactionType'] != 'Auth Only':
                    memo = self.invoice_number_op
                    if partner.ebiz_profile_id.payment_memo_setting == 'dn_pon_pm':
                        memo = " ".join(val for val in [self.invoice_number_op, self.payment_method] if val)
                    payment = self.env['account.payment'].sudo().create(self._prepare_account_payment_values(payment_acq, ebiz_method, partner, memo))

                ebiz_transaction = self.env['payment.transaction'].sudo().create(
                    self._prepare_payment_transaction_values(payment_acq, ebiz_method_tran, partner, sale, payment))
                # In sudo mode to allow writing on callback fields
                ebiz_transaction._set_authorized()
                sale.write({'save_payment_link': False, 'request_amount': 0})
                if transactions['TransactionType'].lower() not in ['auth only', 'authonly']:
                    ebiz_transaction.transaction_type = 'deposit'
                    ebiz_transaction._set_done()
        elif sale:
            resp = ebiz.client.service.MarkApplicationTransactionAsApplied(**{
                'securityToken': ebiz._generate_security_json(),
                'applicationTransactionInternalId': self.payment_internal_id,
            })

            if resp and resp['Status'] == 'Success':
                self.create_payment_on_account(partner)
        return resp

    def payment_applied_for_customer(self, ebiz, partner):
        resp = False
        payment_acq = self.env['payment.provider'].search(
            [('company_id', '=',
              partner.company_id.id if partner.company_id else self.env.company.id),
             ('code', '=', 'ebizcharge')])
        if payment_acq:
            if self.type_id in ['Fixed Amount Auto Payments']:
                resp = ebiz.client.service.MarkRecurringPaymentAsApplied(**{
                    'securityToken': ebiz._generate_security_json(),
                    'paymentInternalId': self.payment_internal_id,
                    'invoiceNumber': self.invoice_number_op if self.invoice_number_op else '',
                })
            else:
                resp = ebiz.client.service.MarkPaymentAsApplied(**{
                    'securityToken': ebiz._generate_security_json(),
                    'paymentInternalId': self.payment_internal_id,
                    'invoiceNumber': self.invoice_number_op if self.invoice_number_op else '',
                })
            if resp['Status'] == 'Success':
                ebiz_method = self.env['account.payment.method.line'].search(
                    [('journal_id', '=', payment_acq.journal_id.id),
                     ('payment_method_id.code', '=', 'ebizcharge')], limit=1)
                payment = self.env['account.payment'].sudo().create(self._prepare_account_payment_values(payment_acq, ebiz_method, partner, ''))
                payment.action_post()
        return resp

    def mark_as_applied(self):
        message_lines = []
        success = 0
        failed = 0
        total = len(self)
        logs_list = []
        unlink_ids = []
        ebiz_cache = {}
        try:
            for record in self:
                message_record = {
                    'customer_name': record.partner_id.name,
                    'customer_id': record.partner_id.id,
                    'invoice_no': record.invoice_number,
                    'status': 'Success'
                }
                invoice = self.env['account.move']
                sale = self.env['sale.order']
                credit = self.env['account.payment']
                if record.invoice_number_op:
                    ref = record.invoice_number_op.split(' ', 1)[0]
                    invoice = invoice.search([('name', '=', ref)])
                    if not invoice:
                        sale = sale.search([('name', '=', ref)])
                    if not invoice and not sale:
                        credit = credit.search([('name', '=', ref)])
                if record.partner_id:
                    instance = record.partner_id.ebiz_profile_id
                    if not instance:
                        raise UserError(f'{record.partner_id.name} have not any Merchant account .Please select Merchant '
                                        f'account on customer profile.')
                    if instance.id not in ebiz_cache:
                        ebiz_cache[instance.id] = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
                    ebiz = ebiz_cache[instance.id]
                    resp = False
                    try:
                        if invoice:
                            resp = record.payment_applied_for_invoice(ebiz, invoice)
                        elif sale:
                            resp = record.payment_applied_for_sale(ebiz, sale, record.partner_id)
                        elif credit:
                            resp = ebiz.client.service.MarkPaymentAsApplied(**{
                                'securityToken': ebiz._generate_security_json(),
                                'paymentInternalId': record.payment_internal_id,
                                'invoiceNumber': record.invoice_number_op,
                            })
                            credit.action_draft()
                            credit.cancel()
                        elif record.type_id in ['Quick Payment', 'Fixed Amount Auto Payments']:
                            resp = record.payment_applied_for_customer(ebiz, record.partner_id)
                        if resp and resp['Status'] == 'Success':
                            success += 1
                            unlink_ids.append(record.id)
                            logs_list.append(record.create_log_lines())
                        else:
                            failed += 1
                            message_record['status'] = 'Failed'
                    except Exception as e:
                        _logger.exception(e)
                        failed += 1
                        message_record['status'] = 'Failed'
                else:
                    failed += 1
                    message_record['status'] = 'Failed'
                message_lines.append(fields.Command.create(message_record))

            if unlink_ids:
                self.wiz_id.payment_lines = [fields.Command.unlink(i) for i in unlink_ids]
            log_ids = self.env['sync.logs'].create(logs_list).ids
            self.wiz_id.transaction_log_lines = [fields.Command.link(i) for i in log_ids]
            wizard = self.env['download.payment.message'].create({'name': 'Download', 'lines_ids': message_lines,
                                                                  'succeeded': success, 'failed': failed,
                                                                  'total': total})
            action = self.env.ref('payment_ebizcharge_crm.wizard_ebiz_download_message_action').read()[0]
            action['context'] = self.env.context
            action['res_id'] = wizard.id
            action['succeeded'] = wizard.succeeded
            action['failed'] = wizard.failed
            return action

        except Exception as e:
            _logger.exception(e)
            raise ValidationError(e)

    def create_log_lines(self):
        dict1 = {
            'type_id': self.type_id,
            'invoice_number': self.invoice_number,
            'partner_id': int(self.customer_id),
            'customer_id': str(self.customer_id),
            'date_paid': self.date_paid,
            'invoice_amount': self.invoice_amount,
            'paid_amount': self.paid_amount,
            'amount_due': self.amount_due,
            'payment_method': self.payment_method,
            'auth_code': self.auth_code,
            'ref_num': self.ref_num,
            'currency_id': self.env.user.currency_id.id,
            'last_sync_date': datetime.now(),
        }
        return dict1

class SyncLogs(models.Model):
    _name = 'sync.logs'
    _description = "Sync Logs"

    sync_date = fields.Datetime('Execution Date/Time', required=True, default=fields.Datetime.now)
    type_id = fields.Char('Type')
    currency_id = fields.Many2one('res.currency')
    invoice_number = fields.Char('Invoice Number')
    partner_id = fields.Many2one('res.partner', 'Customer')
    customer_id = fields.Char('Customer ID')
    date_paid = fields.Char('Date Paid')
    invoice_amount = fields.Float('Invoice Total')
    paid_amount = fields.Float('Amount Paid')
    amount_due = fields.Float('Balance Remaining')
    payment_method = fields.Char('Payment Method')
    auth_code = fields.Char('Auth Code')
    ref_num = fields.Char('Reference Number')
    last_sync_date = fields.Datetime(string="Import Date & Time")

    def clear_logs(self):
        text = f"Are you sure you want to clear {len(self)} payment(s) from the Log?"
        wizard = self.env['wizard.delete.logs.download'].create({
            'record_model': 'sync.logs',
            'text': text
        })
        action = self.env.ref('payment_ebizcharge_crm.wizard_delete_downloads_logs_action').read()[0]
        action['res_id'] = wizard.id
        action['context'] = dict(
            self.env.context,
            record_ids=self.ids,
        )
        return action


class BatchProcessMessage(models.TransientModel):
    _name = "download.payment.message"
    _description = "Download Payment Message"

    name = fields.Char("Name")
    failed = fields.Integer("Failed")
    succeeded = fields.Integer("Succeeded")
    total = fields.Integer("Total")
    lines_ids = fields.One2many('download.payment.message.line', 'message_id')


class BatchProcessMessageLines(models.TransientModel):
    _name = "download.payment.message.line"
    _description = "Download Payment Message Line"

    customer_id = fields.Char('Customer ID')
    customer_name = fields.Char('Customer')
    invoice_no = fields.Char('Number')
    status = fields.Char('Status')
    message_id = fields.Many2one('download.payment.message')
