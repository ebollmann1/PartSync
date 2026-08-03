# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, MissingError, ValidationError
import logging
from .ebiz_charge import message_wizard
_logger = logging.getLogger(__name__)


class BatchProcessing(models.TransientModel):
    _name = 'batch.processing'
    _description = "Batch Processing"

    def domain_users(self):
        return [('create_uid', '=', self.env.user.id)]

    @api.model
    def get_card_type_selection(self):
        return [
            ('A', 'American Express'),
            ('DS', 'Discover'),
            ('M', 'Master Card'),
            ('V', 'VISA'),
        ]

    def get_default_company(self):
        return self.env['ebizcharge.instance.config'].search(
            [('is_active', '=', True), '|', ('company_ids', '=', False),
             ('company_ids', 'in', self.env.context.get('allowed_company_ids'))]).company_ids.ids

    def _default_location_id(self):
        return self.env['ebizcharge.instance.config']._default_instance_id()

    name = fields.Char(string='Batch Processing', default="Batch Processing")
    start_date = fields.Date(string='From Date')
    end_date = fields.Date(string='To Date')
    partner_id = fields.Many2one('res.partner', string='Select Customer',
                                 domain="[('ebiz_internal_id', '!=', False), ('ebiz_profile_id', '=', "
                                        "ebiz_profile_id)]")
    currency_id = fields.Many2one('res.currency')
    transaction_history_line = fields.One2many('sync.batch.processing', 'sync_transaction_id', copy=True)
    transaction_log_lines = fields.Many2many('sync.batch.processed', copy=True,
                                             domain=lambda self: self.domain_users())
    add_filter = fields.Boolean(string='Filters')
    send_receipt = fields.Boolean(string='Send receipt to customer')
    is_surcharge = fields.Boolean(string='sur')
    surcharge_terms = fields.Char(string="Surcharge Terms")
    company_ids = fields.Many2many('res.company', compute='compute_company', default=get_default_company)
    ebiz_profile_id = fields.Many2one('ebizcharge.instance.config', string='EBizCharge Profile',
                                      default=_default_location_id)
    is_surcharge_enabled = fields.Boolean(related='ebiz_profile_id.is_surcharge_enabled')

    is_reopened = fields.Boolean(default=False)
    enable_surcharge_for_all = fields.Selection([('none', 'None'), ('enable', 'Enable'), ('disable', 'Disable')],
                                                default='enable')

    inv_batch_sur_ctrl = fields.Boolean(string='Control Surcharge Per Transaction', related='ebiz_profile_id.inv_batch_sur_ctrl')
    merchant_toggle_sur_per_txn = fields.Boolean(related='ebiz_profile_id.merchant_toggle_sur_per_txn')
    is_surcharge_toggle_visible = fields.Boolean(default=False)
    is_surcharge_toggle_for_all_visible = fields.Boolean(default=False)
    is_surcharge_terms_visible = fields.Boolean(default=False)
    sale_batch_sur_ctrl = fields.Boolean(string='Control Surcharge Per Transaction', related='ebiz_profile_id.sale_batch_sur_ctrl')
    enable_sur_invoice_auto_gpl = fields.Boolean(string='Enable Surcharge', related='ebiz_profile_id.enable_sur_invoice_auto_gpl')
    enable_sur_sales_auto_gpl = fields.Boolean(string='Enable Surcharge', related='ebiz_profile_id.enable_sur_sales_auto_gpl')

    @api.depends('ebiz_profile_id')
    def compute_company(self):
        self.company_ids = self.env.context.get('allowed_company_ids')

    @api.onchange('send_receipt')
    def send_receipt_method(self):
        for i in self:
            for line in i.transaction_history_line:
                line.send_receipt = i.send_receipt

    def _prepare_ebiz_profile(self):
        profile_obj = self.env['ebizcharge.instance.config']
        profile = int(profile_obj.get_upload_instance(active_model='batch.processing', active_id=self))
        if profile:
            self.ebiz_profile_id = profile
            self.start_date = self.ebiz_profile_id._default_get_start()
            self.end_date = self.ebiz_profile_id._default_get_end_date()

    def _set_surcharge_toggle_visibility(self):
        self.is_surcharge_toggle_visible = bool(
            self.merchant_toggle_sur_per_txn and self.is_surcharge_enabled and self.inv_batch_sur_ctrl)
        self.is_surcharge_toggle_for_all_visible = bool(
            self.is_surcharge_enabled and self.merchant_toggle_sur_per_txn)
        self.is_surcharge_terms_visible = self.is_surcharge_enabled
        self.surcharge_terms = self.ebiz_profile_id.batch_terms

    def regenerate_line_ids(self, enable_surcharge_for_all):
        if not self.ebiz_profile_id:
            self._prepare_ebiz_profile()
        self._set_surcharge_toggle_visibility()
        self.enable_surcharge_for_all = enable_surcharge_for_all
        self._create_records_for_batch_processing_list()
        self._create_records_for_batch_processing_logs()

    def update_surcharge_toggle(self, **kwargs):
        """
            It calls When Enable Surcharge for All is toggled On, It will update Surcharge column in all records
        """
        try:
            lines = kwargs['records']
            self = self.env['batch.processing'].search([], limit=1, order='id desc').exists()
            self.enable_surcharge_for_all = 'enable' if kwargs['enable_sur_for_all'] else 'disable'
            if self.inv_batch_sur_ctrl:
                for record in lines:
                    search_invoice_id = self.env['account.move'].browse(int(record['invoice_id'])).exists()
                    payment_token_id = self.env['payment.token'].browse(record['default_card_id'][0]).exists()
                    search_invoice_id.inv_enable_sur = kwargs['enable_sur_for_all'] if payment_token_id.token_type == 'credit' else False
            self.regenerate_line_ids(self.enable_surcharge_for_all)
        except Exception as e:
            _logger.exception(e)
            raise UserError(e)

    def _validate_date_range(self):
        if self.start_date and self.end_date and not self.start_date <= self.end_date:
            return message_wizard('From Date should be lower than the To date!', 'Invalid Date')

    def _create_records_for_batch_processing_list(self):
        try:
            list_of_trans = []
            self.env['sync.batch.processing'].search([]).unlink()
            date_error = self._validate_date_range()
            if date_error:
                return date_error
            if self.ebiz_profile_id:
                filters = self._prepare_batch_processing_list_filters()
                invoices = self.env['account.move'].search(filters)
                for invoice in invoices:
                    partner = invoice.partner_id
                    payment_methods = partner.ebiz_ach_tokens + partner.ebiz_credit_card_ids
                    default_credit_card = payment_methods.filtered(lambda t: t.is_default).exists()
                    if default_credit_card:
                        values = self._prepare_values_for_default_record(invoice, partner, default_credit_card)
                        list_of_trans.append(values)
                self.write({'is_surcharge': self.ebiz_profile_id.is_surcharge_enabled,
                            'surcharge_terms': self.ebiz_profile_id.batch_terms})
            self.env['sync.batch.processing'].create(list_of_trans)
        except Exception as e:
            raise ValidationError(e)

    def _create_records_for_batch_processing_logs(self):
        try:
            list_of_trans = []
            date_error = self._validate_date_range()
            if date_error:
                return date_error
            if self.ebiz_profile_id:
                filters = self._prepare_batch_processing_logs_filters()
                list_of_trans = self.env['sync.batch.processed'].search(filters).filtered(
                    lambda i: i.date_paid and i.date_paid.date() >= self.start_date and i.date_paid.date() <= self.end_date)
            self.write({'transaction_log_lines': [fields.Command.set(list_of_trans.ids)]})
        except Exception as e:
            raise ValidationError(e)

    def _prepare_batch_processing_list_filters(self):
        filters = [('payment_state', '!=', 'paid'),
                   ('amount_residual', '>', 0),
                   ('ebiz_invoice_status', 'in', ('delete', 'default', 'partially_received')),
                   ('state', '=', 'posted'),
                   ('move_type', '=', 'out_invoice')]

        if self.end_date:
            filters.append(('date', '<=', self.end_date))

        if self.start_date:
            filters.append(('date', '>=', self.start_date))

        if self.partner_id:
            filters.append(('partner_id', '=', self.partner_id.id))

        if self.ebiz_profile_id:
            filters.append(('partner_id.ebiz_profile_id', '=', self.ebiz_profile_id.id))

        return filters

    def _prepare_batch_processing_logs_filters(self):
        filters = []
        if self.partner_id:
            filters.append(('customer_name', '=', self.partner_id.id))
        if self.ebiz_profile_id:
            filters.append(('customer_name.ebiz_profile_id', '=', self.ebiz_profile_id.id))
        return filters

    def create_default_records(self):
        self._set_surcharge_toggle_visibility()
        self.regenerate_line_ids('none')

    def _prepare_values_for_default_record(self, invoice, partner, default_credit_card):
        values = {
            'name': invoice['name'],
            'customer_name': partner.id,
            'email': partner.email,
            'customer_id': str(partner.id),
            'invoice_id': invoice.id,
            'invoice_date': invoice.date,
            'invoice_date_due': invoice.invoice_date_due,
            'currency_id': invoice.currency_id.id,
            'sales_person': self.env.user.id,
            'amount': invoice.amount_total,
            'amount_residual': invoice.amount_residual,
            'payment_method': default_credit_card.get_encrypted_name(),
            'default_card_id': default_credit_card.id,
            'generated_link': invoice.save_payment_link,
            'sync_transaction_id': self.id,
        }
        inv_enable_sur = self.enable_surcharge_for_all != 'disable' and default_credit_card.token_type == 'credit'
        values['inv_enable_sur'] = inv_enable_sur
        invoice.inv_enable_sur = inv_enable_sur
        return values

    def get_list_of_invoices(self, filters):
        list_of_invoices = []
        for invoice in self.env['account.move'].search(filters):
            partner = invoice.partner_id
            default_credit_card = (partner.ebiz_ach_tokens + partner.ebiz_credit_card_ids).filtered(
                lambda t: t.is_default).exists()
            if default_credit_card:
                list_of_invoices.append(self._prepare_values_for_default_record(invoice, partner, default_credit_card))
        return list_of_invoices

    def action_open_batch_processing(self):
        profile_obj = self.env['ebizcharge.instance.config']
        profile = int(profile_obj.get_upload_instance(active_model='batch.processing', active_id=self))
        record = self
        if profile:
            ebiz_profile_id = self.env['ebizcharge.instance.config'].browse(profile)
            record = self.create({'ebiz_profile_id': profile,
                                  'start_date': ebiz_profile_id._default_get_start(),
                                  'end_date': ebiz_profile_id._default_get_end_date()})
            record.regenerate_line_ids('none')
        return {
            "name": _("Batch Processing"),
            "type": "ir.actions.act_window",
            "res_model": "batch.processing",
            "res_id": record.id,
            'view_id': self.env.ref('payment_ebizcharge_crm.form_view_batch_processing', False).id,
            "view_mode": "form",
            "target": "inline",
        }


class ListSyncBatch(models.TransientModel):
    _name = 'sync.batch.processing'
    _order = 'invoice_id asc'
    _description = "Sync Batch Processing"

    sync_date = fields.Datetime(string='Execution Date/Time', required=True, default=fields.Datetime.now)
    sync_transaction_id = fields.Many2one('batch.processing', string='Partner Reference', required=True,
                                          ondelete='cascade', index=True, copy=False)
    ebiz_profile_id = fields.Many2one('ebizcharge.instance.config', string='EBizCharge Profile',
                                      related='sync_transaction_id.ebiz_profile_id')
    inv_batch_sur_ctrl = fields.Boolean(string='Control Surcharge Per Transaction', related='ebiz_profile_id.inv_batch_sur_ctrl')
    is_surcharge_enabled = fields.Boolean(string="Surcharge Enabled", related='sync_transaction_id.is_surcharge')
    merchant_toggle_sur_per_txn = fields.Boolean(related='ebiz_profile_id.merchant_toggle_sur_per_txn')
    is_surcharge_toggle_visible = fields.Boolean(related='sync_transaction_id.is_surcharge_toggle_for_all_visible')
    inv_enable_sur = fields.Boolean(string='Surcharge')
    enable_surcharge_for_all = fields.Boolean(
        compute='_compute_enable_surcharge_for_all',
        inverse='_inverse_enable_surcharge_for_all',
    )

    @api.depends('inv_enable_sur', 'token_type')
    def _compute_enable_surcharge_for_all(self):
        for rec in self:
            # ACH is neutral (True) — doesn't pull the header toggle OFF
            # when all credit records have surcharge enabled.
            rec.enable_surcharge_for_all = rec.token_type == 'ach' or rec.inv_enable_sur

    def _inverse_enable_surcharge_for_all(self):
        for rec in self:
            if rec.token_type == 'ach':
                continue
            rec.inv_enable_sur = rec.enable_surcharge_for_all

    name = fields.Char(string='Number')
    customer_name = fields.Many2one('res.partner', string='Customer')
    customer_id = fields.Char(string='Customer ID')
    invoice_id = fields.Many2one('account.move', string='Invoice')
    account_holder = fields.Char(string='Account Holder')
    date_time = fields.Datetime(string='Date Time')
    currency_id = fields.Many2one('res.currency', string='Company Currency')
    amount = fields.Float(string='Invoice Total')
    amount_residual = fields.Float(string='Balance')
    tax = fields.Char(string='Tax Excluded')
    card_no = fields.Char(string='Card Number')
    status = fields.Char(string='Status')
    email = fields.Char(string='Email')
    invoice_date = fields.Date(string='Invoice Date')
    invoice_date_due = fields.Date(string='Due Date')
    sales_person = fields.Many2one('res.users', string='Sales Person')
    payment_method = fields.Char(string='Payment Method')
    default_card_id = fields.Many2one('payment.token', string='Default Credit Card ID')
    token_type = fields.Selection([('credit', 'Credit Card'), ('ach', 'ACH')], related='default_card_id.token_type')
    send_receipt = fields.Boolean(string='Send receipt to customer')
    generated_link = fields.Char(string='Generated Link')

    def create_log_lines(self):
        list_of_invoices = []
        for record in self:
            odoo_invoice = record.invoice_id
            transaction_id = odoo_invoice.transaction_ids[0] if odoo_invoice.transaction_ids else False
            trans_status = 'Declined'
            if transaction_id and str(transaction_id.state) == 'done':
                trans_status = 'Success'
            if transaction_id:
                dict1 = {
                    "name": record.name,
                    "customer_name": odoo_invoice.partner_id.id,
                    "customer_id": odoo_invoice.partner_id.id,
                    "date_paid": transaction_id.last_state_change if transaction_id else False,
                    "currency_id": record.currency_id.id,
                    "amount_paid": record.amount,
                    "transaction_status": trans_status,
                    "payment_method": record.payment_method,
                    "auth_code": transaction_id.ebiz_auth_code,
                    "transaction_ref": transaction_id.provider_reference,
                    'email': record.email if record.send_receipt else "NA",
                    'is_surcharged': odoo_invoice.was_inv_sur_enabled,
                }
                list_of_invoices.append(dict1)

        log_ids = self.env['sync.batch.processed'].create(list_of_invoices).ids
        self.sync_transaction_id.transaction_log_lines = [fields.Command.link(log_id) for log_id in log_ids]

    def process_invoices(self):
        """
            Email the receipt to customer, if email receipts templates not there in odoo, it will fetch.
            return: wizard to select the receipt template
        """
        try:
            if any(record.generated_link for record in self) and 'for_batch_processing' not in self.env.context:
                text = f"One or more documents selected have pending payment links. Processing payments for these documents will invalidate the existing links. Do you want to continue?"
                wizard = self.env['wizard.receive.email.payment.link'].create({
                    "text": text,
                    "batch_ids": [fields.Command.set(self.ids)],
                })
                action = self.env.ref('payment_ebizcharge_crm.wizard_received_email_pay_payment_link').read()[0]
                action['res_id'] = wizard.id
                return action
            success = 0
            total_count = len(self)

            message_lines = []
            unlink_ids = []
            for record in self:
                search_invoice = record.invoice_id
                search_invoice.inv_enable_sur = record.inv_enable_sur
                search_invoice.sync_to_ebiz()
                search_invoice.ebiz_batch_procssing_reg(record.default_card_id.id, record.send_receipt)
                is_done = bool(search_invoice.transaction_ids and search_invoice.transaction_ids[0].state == 'done')
                if is_done:
                    success += 1
                    unlink_ids.append(record.id)
                search_invoice.was_inv_sur_enabled = record.inv_enable_sur
                message_lines.append(fields.Command.create({
                    'customer_id': record.customer_id,
                    'customer_name': record.customer_name.name,
                    'invoice_no': record.name,
                    'status': 'Success' if is_done else 'Failed',
                }))
            self.create_log_lines()
            if unlink_ids:
                self.sync_transaction_id.transaction_history_line = [fields.Command.unlink(i) for i in unlink_ids]
            wizard = self.env['batch.process.message'].create({'name': "Batch Process", 'lines_ids': message_lines,
                                                               'success_count': success, 'total': total_count})
            return {
                'type': 'ir.actions.act_window',
                'name': _('Batch Processing Results'),
                'res_model': 'batch.process.message',
                'res_id': wizard.id,
                'target': 'new',
                'view_mode': 'form',
                'views': [[False, 'form']],
                'context': self.env.context
            }

        except MissingError as b:
            self.sync_transaction_id.regenerate_line_ids('none')
            return {
                'type': 'ir.actions.act_window',
                'name': _('Record Updated!!!'),
                'res_model': 'message.wizard',
                'target': 'new',
                'view_mode': 'form',
                'views': [[False, 'form']],
                'context': {
                    'message': 'There was a change in the record, Invoices refreshed! Please try now',
                },
            }

        except Exception as e:
            _logger.exception(e)
            raise UserError(e)
    
    def view_payment_methods(self, *args, **kwargs):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Payment Methods',
            'res_model': 'res.partner',
            'res_id': kwargs['values'],
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
            'flags': {'mode': 'readonly'},
            'context': {'create': False},
        }



class SyncBatchProcessed(models.TransientModel):
    _name = 'sync.batch.processed'
    _order = 'date_paid desc'
    _description = "Sync Batch Processed"

    sync_date = fields.Datetime(string='Execution Date/Time', required=True, default=fields.Datetime.now)
    name = fields.Char(string='Invoice Number')
    customer_name = fields.Many2one('res.partner', string='Customer')
    customer_id = fields.Char(string='Customer ID')
    date_paid = fields.Datetime(string='Date & Time Paid')
    currency_id = fields.Many2one('res.currency', string='Company Currency')
    amount_paid = fields.Float(string='Amount Paid')
    transaction_status = fields.Char(string='Transaction Status')
    email = fields.Char(string='Receipt Sent To (Email)')
    payment_method = fields.Char(string='Payment Method')
    auth_code = fields.Char(string='Auth Code')
    transaction_ref = fields.Char(string='Reference Number')
    is_surcharged = fields.Boolean(string='Surcharge')

    def clear_logs(self):
        if not self:
            raise UserError('Please select a record first!')
        text = f"Are you sure you want to clear {len(self)} invoice(s) from the Log?"
        wizard = self.env['wizard.delete.upload.logs'].create({
            "record_id": 0,
            "record_model": 'invoice',
            "text": text,
        })
        action = self.env.ref('payment_ebizcharge_crm.wizard_delete_upload_logs').read()[0]
        action['res_id'] = wizard.id
        action['context'] = dict(
            self.env.context,
            list_of_records=self.ids,
            model='sync.batch.processed',
        )
        return action


class SyncBatchLog(models.TransientModel):
    _name = 'sync.batch.log'
    _description = "Sync Batch Log"

    sync_date = fields.Datetime('Execution Date/Time', required=True, default=fields.Datetime.now)
    name = fields.Char(string='Invoice Number')
    customer_name = fields.Many2one('res.partner', string='Customer')
    customer_id = fields.Char(string='Customer ID')
    date_paid = fields.Datetime(string='Date & Time Paid')
    currency_id = fields.Many2one('res.currency', string='Company Currency')
    amount_paid = fields.Float(string='Amount Paid')
    transaction_status = fields.Char(string='Transaction Status')
    email = fields.Char(string='Receipt Sent To (Email)', related='customer_name.email')
    payment_method = fields.Char(string='Payment Method')
    auth_code = fields.Char(string='Auth Code')
    transaction_ref = fields.Char(string='Reference Number')


class BatchProcessMessage(models.TransientModel):
    _name = "batch.process.message"
    _description = "Batch Process Message"

    name = fields.Char(string="Name")
    success_count = fields.Integer(string="Success Count")
    total = fields.Integer(string="Total")
    lines_ids = fields.One2many('batch.processing.message.line', 'message_id')


class BatchProcessMessageLines(models.TransientModel):
    _name = "batch.processing.message.line"
    _description = "Batch Processing Message Line"

    customer_id = fields.Char(string='Customer ID')
    customer_name = fields.Char(string='Customer Name')
    invoice_no = fields.Char(string='Number')
    status = fields.Char(string='Status')
    message_id = fields.Many2one('batch.process.message')
