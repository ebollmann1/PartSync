# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
from io import BytesIO
import base64

_logger = logging.getLogger(__name__)


class UploadCustomers(models.Model):
    _name = 'upload.customers'
    _description = "Upload Customers"

    def _get_all_instance(self):
        all_list = [("0", "All")]
        profiles = self.env['ebizcharge.instance.config'].search([('is_valid_credential', '=', True),
                                                                  ('is_active', '=', True), '|',
                                                                  ('company_ids', '=', False),
                                                                  ('company_ids', 'in', self.env.companies.ids)])
        instance = [(str(profile.id), profile.name) for profile in profiles]
        return all_list + instance

    def get_default_company(self):
        return self.env['ebizcharge.instance.config'].search(
            [('is_active', '=', True), '|', ('company_ids', '=', False),
             ('company_ids', 'in', self.env.context.get('allowed_company_ids'))]).company_ids.ids

    def domain_users(self):
        return [('user_id', '=', self.env.user.id)]

    def _get_logs_domain(self):
        if self.ebiz_profile_id == '0':
            all_profiles = self.env['ebizcharge.instance.config'].search(
                [('is_valid_credential', '=', True), ('is_active', '=', True), '|', ('company_ids', '=', False),
                 ('company_ids', 'in', self.env.companies.ids)])
            instances = all_profiles.ids
        else:
            instances = [int(self.ebiz_profile_id)]
        return [('customer_id.ebiz_profile_id', 'in', instances)]

    # Computed Many2many instead of a sync_log_id-backed One2many: logs are visible based on the
    # current ebiz_profile_id scope, independent of which upload.customers parent created them.
    logs_line = fields.Many2many('logs.of.customers', compute='_compute_logs_line')
    company_ids = fields.Many2many('res.company', compute='compute_company', default=get_default_company)
    add_filter = fields.Boolean(string='Filters')
    name = fields.Char(default='Upload Customers')
    transaction_history_line = fields.One2many('list.of.customers', 'sync_transaction_id', copy=True)
    ebiz_profile_id = fields.Selection(selection=_get_all_instance)

    @api.depends('ebiz_profile_id')
    def compute_company(self):
        self.company_ids = self.env.context.get('allowed_company_ids')

    @api.depends('ebiz_profile_id')
    def _compute_logs_line(self):
        for rec in self:
            rec.logs_line = self.env['logs.of.customers'].search(rec._get_logs_domain())

    def action_open_upload_customers(self):
        rec = self.env['upload.customers'].create({})
        rec.create_default_records()
        return {
            'name': _('Upload Customers'),
            'type': 'ir.actions.act_window',
            'res_model': 'upload.customers',
            'res_id': rec.id,
            'view_id': self.env.ref('payment_ebizcharge_crm.form_view_request_upload_customers', False).id,
            'view_mode': 'form',
            'target': 'inline',
        }

    def create_default_records(self):
        profile_obj = self.env['ebizcharge.instance.config']
        profile = profile_obj.get_upload_instance(active_model='upload.customers', active_id=self)
        if profile:
            self.ebiz_profile_id = profile
        partner_obj = self.env['res.partner']
        # ebiz_internal_id is set once a customer has been synced; those belong in Logs, not List.
        if self.ebiz_profile_id == '0':
            all_profiles = profile_obj.search(
                [('is_valid_credential', '=', True), ('is_active', '=', True), '|', ('company_ids', '=', False),
                 ('company_ids', 'in', self.env.context.get('allowed_company_ids'))])
            list_of_customers = partner_obj.search([('ebiz_profile_id', 'in', all_profiles.ids),
                                                    ('customer_rank', '>', 0), ('active', '=', True),
                                                    ('ebiz_internal_id', '=', False)])
        else:
            list_of_customers = partner_obj.search([('ebiz_profile_id', '=', int(self.ebiz_profile_id)),
                                                    ('customer_rank', '>', 0), ('active', '=', True),
                                                    ('ebiz_internal_id', '=', False)])

        self.transaction_history_line = [fields.Command.clear()] + [
            fields.Command.create({'customer_id': customer.id, 'sync_transaction_id': self.id})
            for customer in list_of_customers
        ]



class BillExcel(models.TransientModel):
    _name = "bill.excel"
    _description = "Bill Excel"

    excel_file = fields.Binary('Excel File')
    file_name = fields.Char('Excel Name', size=64)


class ListOfCustomers(models.Model):
    _name = 'list.of.customers'
    _description = "List of Customers"
    _order = 'create_date desc'

    sync_transaction_id = fields.Many2one('upload.customers', string='Partner Reference', required=True,
                                          ondelete='cascade', index=True, copy=False)
    name = fields.Char(string='Number')
    customer_id = fields.Many2one('res.partner', string='Customer')
    email_id = fields.Char(string='Email', related='customer_id.email')
    customer_phone = fields.Char('Phone', related='customer_id.phone')
    customer_city = fields.Char('City', related='customer_id.city')
    street = fields.Char('Street', related='customer_id.street')
    country = fields.Many2one('res.country', 'Country', related='customer_id.country_id')
    sync_status = fields.Char(string='Sync Status', related='customer_id.sync_response')
    last_sync_date = fields.Datetime(string="Upload Date & Time", related='customer_id.last_sync_date')

    def upload_customers(self):
        try:
            if not self:
                raise UserError('Please select a record first!')
            list_ids = [record.customer_id.id for record in self]
            action = self[0].customer_id.sync_multi_customers_from_upload_customers(list_ids)
            self.filtered(lambda r: r.customer_id.ebiz_internal_id).unlink()
            return action
        except Exception as e:
            raise UserError(e)

    def export_customers(self):
        if not self:
            raise UserError('Please select a record first!')
        column_names = ['Customer ID #', 'Customer', 'Email', 'Phone', 'Street', 'City', 'Country',
                        'Upload Date & Time', 'Upload Status']
        worksheet, workbook, header_style, text_center = self.env['ebizcharge.instance.config'].export_generic_method(
            sheet_name='Customers', columns=column_names)
        i = 4
        for record in self:
            worksheet[0].write(i, 1, str(record.customer_id.id) if record.customer_id else '', text_center)
            worksheet[0].write(i, 2, record.customer_id.name or '', text_center)
            worksheet[0].write(i, 3, record.email_id or '', text_center)
            worksheet[0].write(i, 4, record.customer_phone or '', text_center)
            worksheet[0].write(i, 5, record.street or '', text_center)
            worksheet[0].write(i, 6, record.customer_city or '', text_center)
            worksheet[0].write(i, 7, record.country.name or '', text_center)
            worksheet[0].write(i, 8, str(record.last_sync_date or ''), text_center)
            worksheet[0].write(i, 9, record.sync_status or '', text_center)
            i += 1
        fp = BytesIO()
        workbook.save(fp)
        export_id = self.env['bill.excel'].create(
            {'excel_file': base64.encodebytes(fp.getvalue()), 'file_name': 'Customers.xls'})
        return {
            'type': 'ir.actions.act_url',
            'url': f'web/content/?model=bill.excel&field=excel_file&download=true&id={export_id.id}&filename=Customers.xls',
            'target': 'new',
        }

    def delete_customers(self):
        if not self:
            raise UserError('Please select a record first!')
        synced = self.filtered(lambda r: r.customer_id.ebiz_internal_id)
        if not synced:
            raise UserError('Selected customer(s) must be synced prior to being deactivated.')
        text = f"Are you sure you want to deactivate {len(self)} customer(s) in Odoo and EBizCharge Hub?"
        wizard = self.env['wizard.inactive.customers'].create({
            "record_id": self[0].sync_transaction_id.id,
            "record_model": self._name,
            "text": text,
        })
        action = self.env.ref('payment_ebizcharge_crm.wizard_delete_inactive_customers').read()[0]
        action['res_id'] = wizard.id
        action['context'] = dict(self.env.context, selected_line_ids=synced.ids)
        return action


class LogsOfCustomers(models.Model):
    _name = 'logs.of.customers'
    _description = "Logs of Customers"
    _order = 'last_sync_date desc'

    sync_log_id = fields.Many2one('upload.customers', string='Partner Reference',
                                  ondelete='cascade', index=True, copy=False)
    name = fields.Char(string='Customer')
    customer_id = fields.Many2one('res.partner', string='Customer')
    email_id = fields.Char(string='Email')
    customer_phone = fields.Char('Phone')
    sync_status = fields.Char(string='Sync Status')
    last_sync_date = fields.Datetime(string="Upload Date & Time")
    street = fields.Char('Address')
    user_id = fields.Many2one('res.users', 'User')

    def export_logs(self):
        if not self:
            raise UserError('Please select a record first!')
        column_names = ['Customer ID #', 'Customer', 'Email', 'Phone', 'Upload Date & Time', 'Upload Status']
        worksheet, workbook, header_style, text_center = self.env['ebizcharge.instance.config'].export_generic_method(
            sheet_name='Customer Logs', columns=column_names)
        i = 4
        for record in self:
            worksheet[0].write(i, 1, str(record.customer_id.id) if record.customer_id else '', text_center)
            worksheet[0].write(i, 2, record.customer_id.name or '', text_center)
            worksheet[0].write(i, 3, record.email_id or '', text_center)
            worksheet[0].write(i, 4, record.customer_phone or '', text_center)
            worksheet[0].write(i, 5, str(record.last_sync_date or ''), text_center)
            worksheet[0].write(i, 6, record.sync_status or '', text_center)
            i += 1
        fp = BytesIO()
        workbook.save(fp)
        export_id = self.env['bill.excel'].create(
            {'excel_file': base64.encodebytes(fp.getvalue()), 'file_name': 'Customer Logs.xls'})
        return {
            'type': 'ir.actions.act_url',
            'url': f'web/content/?model=bill.excel&field=excel_file&download=true&id={export_id.id}&filename=Customer Logs.xls',
            'target': 'new',
        }

    def clear_logs(self):
        if not self:
            raise UserError('Please select a record first!')
        text = f"Are you sure you want to clear {len(self)} customer(s) from the Log?"
        wizard = self.env['wizard.delete.upload.logs'].create({
            "record_id": self[0].sync_log_id.id or 0,
            "record_model": 'customer',
            "text": text,
        })
        action = self.env.ref('payment_ebizcharge_crm.wizard_delete_upload_logs').read()[0]
        action['res_id'] = wizard.id
        action['context'] = dict(
            self.env.context,
            list_of_records=self.ids,
            model='logs.of.customers',
        )
        return action
