# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
from io import BytesIO
import base64

_logger = logging.getLogger(__name__)


class UploadCreditNotes(models.Model):
    _name = 'upload.credit.notes'
    _description = "Upload Credit Notes"

    def _get_logs_domain(self):
        if self.ebiz_profile_id == '0':
            all_profiles = self.env['ebizcharge.instance.config'].search(
                [('is_valid_credential', '=', True), ('is_active', '=', True), '|', ('company_ids', '=', False),
                 ('company_ids', 'in', self.env.context.get('allowed_company_ids'))])
            instances = all_profiles.ids
        else:
            instances = [int(self.ebiz_profile_id)]
        return [('partner_id.ebiz_profile_id', 'in', instances)]

    def get_default_company(self):
        companies = self.env['ebizcharge.instance.config'].search(
            [('is_active', '=', True), '|', ('company_ids', '=', False), (
                'company_ids', 'in', self.env.context.get('allowed_company_ids'))]).mapped('company_ids').ids
        return companies

    def _get_all_instance(self):
        all_list = [("0", "All")]
        profiles = self.env['ebizcharge.instance.config'].search([('is_valid_credential', '=', True),
                                                                  ('is_active', '=', True), '|',
                                                                  ('company_ids', '=', False),
                                                                  ('company_ids', 'in', self.env.companies.ids)])
        instance = [(str(profile.id), profile.name) for profile in profiles]
        return all_list + instance

    name = fields.Char(default='Upload Credit Notes')
    add_filter = fields.Boolean(string='Filters')
    invoice_lines = fields.One2many('list.credit.notes', 'sync_invoice_id', copy=True)
    # Computed Many2many instead of a sync_log_id-backed One2many: logs are visible based on the
    # current ebiz_profile_id scope, independent of which upload.credit.notes parent created them.
    logs_line = fields.Many2many('logs.credit.notes', compute='_compute_logs_line')
    company_ids = fields.Many2many('res.company', compute='compute_company', default=get_default_company)
    ebiz_profile_id = fields.Selection(selection=_get_all_instance)

    @api.depends('ebiz_profile_id')
    def compute_company(self):
        self.company_ids = self.env.context.get('allowed_company_ids')

    @api.depends('ebiz_profile_id')
    def _compute_logs_line(self):
        for rec in self:
            rec.logs_line = self.env['logs.credit.notes'].search(rec._get_logs_domain())

    def action_open_upload_credit_notes(self):
        rec = self.env['upload.credit.notes'].create({})
        rec.create_default_records()
        return {
            'name': _('Upload Credit Notes'),
            'type': 'ir.actions.act_window',
            'res_model': 'upload.credit.notes',
            'res_id': rec.id,
            'view_id': self.env.ref('payment_ebizcharge_crm.upload_credit_notes_form_view', False).id,
            'view_mode': 'form',
            'target': 'inline',
        }

    def create_default_records(self):
        profile_obj = self.env['ebizcharge.instance.config']
        profile = profile_obj.get_upload_instance(active_model='upload.credit.notes', active_id=self)
        if profile:
            self.ebiz_profile_id = profile
        account_obj = self.env['account.move']
        # ebiz_internal_id is set once a credit note has been synced; those belong in Logs, not List.
        if self.ebiz_profile_id == '0':
            all_profiles = profile_obj.search(
                [('is_valid_credential', '=', True), ('is_active', '=', True), '|', ('company_ids', '=', False),
                 ('company_ids', 'in', self.env.context.get('allowed_company_ids'))])
            list_of_invoices = account_obj.search(
                [("move_type", "=", "out_refund"), ("state", "=", 'posted'),
                 ('partner_id.ebiz_profile_id', 'in', all_profiles.ids), ('ebiz_internal_id', '=', False)])
        else:
            list_of_invoices = account_obj.search(
                [("move_type", "=", "out_refund"), ("state", "=", 'posted'),
                 ('partner_id.ebiz_profile_id', '=', int(self.ebiz_profile_id)),
                 ('ebiz_internal_id', '=', False)])

        self.invoice_lines = [fields.Command.clear()] + [
            fields.Command.create({
                'invoice': invoice.id,
                'partner_id': invoice.partner_id.id,
                'currency_id': self.env.user.currency_id.id,
                'sync_invoice_id': self.id,
            })
            for invoice in list_of_invoices
        ]


class ListCreditNotes(models.Model):
    _name = 'list.credit.notes'
    _description = "List Credit Notes"
    _order = 'create_date desc'

    sync_invoice_id = fields.Many2one('upload.credit.notes', string='Partner Reference', required=True,
                                      ondelete='cascade', index=True, copy=False)
    invoice = fields.Many2one('account.move', string='Number')
    invoice_id = fields.Integer(string='Invoice ID', related='invoice.id')
    state = fields.Char(string='State')
    partner_id = fields.Many2one('res.partner', string='Customer')
    amount_total_signed = fields.Monetary(string='Amount Total', related='invoice.amount_total')
    amount_residual_signed = fields.Monetary(string='Balance Remaining', related='invoice.amount_residual')
    amount_untaxed = fields.Monetary(string='Tax Excluded', related='invoice.amount_untaxed_signed')
    currency_id = fields.Many2one("res.currency", string="Currency", readonly=True, required=True)
    invoice_date_due = fields.Date('Due Date', related='invoice.invoice_date_due')
    last_sync_date = fields.Datetime('Upload Date & Time', related='invoice.last_sync_date')
    sync_status = fields.Char('Sync Status', related='invoice.sync_response')
    invoice_date = fields.Date('Invoice Date', related='invoice.invoice_date')

    def upload_invoice(self):
        if not self:
            raise UserError('Please select a record first!')
        list_ids = self.mapped('invoice').ids
        action = self[0].invoice.with_context({'credit': 'credit_notes'}).sync_multi_customers_from_upload_invoices(list_ids)
        self.filtered(lambda r: r.invoice.ebiz_internal_id).unlink()
        return action

    def export_orders(self):
        if not self:
            raise UserError('Please select a record first!')
        column_names = ['Number', 'Customer', 'Customer ID', 'Invoice Total', 'Balance Remaining', 'Invoice Date',
                        'Due Date', 'Upload Date & Time', 'Sync Status']
        worksheet, workbook, header_style, text_center = self.env['ebizcharge.instance.config'].export_generic_method(
            sheet_name='Credit_notes', columns=column_names)
        i = 4
        for record in self:
            worksheet[0].write(i, 1, record.invoice.name or '', text_center)
            worksheet[0].write(i, 2, record.partner_id.name or '', text_center)
            worksheet[0].write(i, 3, str(record.partner_id.id) if record.partner_id else '', text_center)
            worksheet[0].write(i, 4, record.amount_total_signed or '', text_center)
            worksheet[0].write(i, 5, record.amount_residual_signed or 0, text_center)
            worksheet[0].write(i, 6, str(record.invoice_date) if record.invoice_date else '', text_center)
            worksheet[0].write(i, 7, str(record.invoice_date_due) if record.invoice_date_due else '', text_center)
            worksheet[0].write(i, 8, str(record.last_sync_date) if record.last_sync_date else '', text_center)
            worksheet[0].write(i, 9, record.sync_status or '', text_center)
            i += 1
        fp = BytesIO()
        workbook.save(fp)
        export_id = self.env['bill.excel'].create(
            {'excel_file': base64.encodebytes(fp.getvalue()), 'file_name': 'Credit_notes.xls'})
        return {
            'type': 'ir.actions.act_url',
            'url': f'web/content/?model=bill.excel&field=excel_file&download=true&id={export_id.id}&filename=Credit_notes.xls',
            'target': 'new',
        }


class LogCreditNotes(models.Model):
    _name = 'logs.credit.notes'
    _description = "Logs Credit Notes"
    _order = 'last_sync_date desc'

    sync_log_id = fields.Many2one('upload.credit.notes', string='Partner Reference',
                                  ondelete='cascade', index=True, copy=False)
    name = fields.Char(string='Number')
    invoice = fields.Many2one('account.move', string='Invoice Number')
    partner_id = fields.Many2one("res.partner", string='Customer')
    currency_id = fields.Many2one("res.currency", string="Currency", readonly=True, required=True)
    amount_untaxed = fields.Monetary(string='Tax Excluded')
    amount_total_signed = fields.Monetary(string='Invoice Total')
    amount_residual_signed = fields.Monetary(string='Balance Remaining')
    invoice_date_due = fields.Date('Due Date')
    invoice_date = fields.Date('Invoice Date')
    last_sync_date = fields.Datetime('Upload Date & Time')
    sync_status = fields.Char('Sync Status')

    def export_logs(self):
        if not self:
            raise UserError('Please select a record first!')
        column_names = ['Number', 'Customer', 'Customer ID', 'Invoice Total', 'Balance Remaining', 'Invoice Date',
                        'Due Date', 'Upload Date & Time', 'Sync Status']
        worksheet, workbook, header_style, text_center = self.env['ebizcharge.instance.config'].export_generic_method(
            sheet_name='Credit_notes Logs', columns=column_names)
        i = 4
        for record in self:
            worksheet[0].write(i, 1, record.invoice.name or '', text_center)
            worksheet[0].write(i, 2, record.partner_id.name or '', text_center)
            worksheet[0].write(i, 3, str(record.partner_id.id) if record.partner_id else '', text_center)
            worksheet[0].write(i, 4, record.amount_total_signed or '', text_center)
            worksheet[0].write(i, 5, record.amount_residual_signed or 0, text_center)
            worksheet[0].write(i, 6, str(record.invoice_date) if record.invoice_date else '', text_center)
            worksheet[0].write(i, 7, str(record.invoice_date_due) if record.invoice_date_due else '', text_center)
            worksheet[0].write(i, 8, str(record.last_sync_date) if record.last_sync_date else '', text_center)
            worksheet[0].write(i, 9, str(record.sync_status) if record.sync_status else '', text_center)
            i += 1
        fp = BytesIO()
        workbook.save(fp)
        export_id = self.env['bill.excel'].create(
            {'excel_file': base64.encodebytes(fp.getvalue()), 'file_name': 'Credit_notes Logs.xls'})
        return {
            'type': 'ir.actions.act_url',
            'url': f'web/content/?model=bill.excel&field=excel_file&download=true&id={export_id.id}&filename=Credit_notes Logs.xls',
            'target': 'new',
        }

    def clear_logs(self):
        if not self:
            raise UserError('Please select a record first!')
        text = f"Are you sure you want to clear {len(self)} credit note(s) from the Log?"
        wizard = self.env['wizard.delete.upload.logs'].create({
            "record_id": self[0].sync_log_id.id or 0,
            "record_model": 'credit note',
            "text": text,
        })
        action = self.env.ref('payment_ebizcharge_crm.wizard_delete_upload_logs').read()[0]
        action['res_id'] = wizard.id
        action['context'] = dict(
            self.env.context,
            list_of_records=self.ids,
            model='logs.credit.notes',
        )
        return action
