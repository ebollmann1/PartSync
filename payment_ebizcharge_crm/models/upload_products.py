# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
from io import BytesIO
import base64

_logger = logging.getLogger(__name__)


class UploadProducts(models.Model):
    _name = 'upload.products'
    _description = "Upload Products"

    def _get_logs_domain(self):
        if self.ebiz_profile_id == '0':
            all_profiles = self.env['ebizcharge.instance.config'].search(
                [('is_valid_credential', '=', True), ('is_active', '=', True), '|', ('company_ids', '=', False),
                 ('company_ids', 'in', self.env.context.get('allowed_company_ids'))])
            instances = all_profiles.ids
        else:
            instances = [int(self.ebiz_profile_id)]
        return [('product_name.ebiz_profile_id', 'in', instances)]

    def _get_all_instance(self):
        all_list = [("0", "All")]
        profiles = self.env['ebizcharge.instance.config'].search([('is_valid_credential', '=', True),
                                                                  ('is_active', '=', True), '|',
                                                                  ('company_ids', '=', False),
                                                                  ('company_ids', 'in', self.env.companies.ids)])
        instance = [(str(profile.id), profile.name) for profile in profiles]
        return all_list + instance

    def get_default_company(self):
        companies = self.env['ebizcharge.instance.config'].search(
            [('is_active', '=', True), '|', ('company_ids', '=', False), (
                'company_ids', 'in', self.env.context.get('allowed_company_ids'))]).mapped('company_ids').ids
        return companies

    name = fields.Char(default='Upload Products')
    add_filter = fields.Boolean(string='Filters')
    transaction_history_line = fields.One2many('list.of.products', 'sync_transaction_id', copy=True)
    # Computed Many2many instead of a sync_log_id-backed One2many: logs are visible based on the
    # current ebiz_profile_id scope, independent of which upload.products parent created them.
    logs_line = fields.Many2many('logs.of.products', compute='_compute_logs_line')
    ebiz_profile_id = fields.Selection(selection=_get_all_instance)
    company_ids = fields.Many2many('res.company', compute='compute_company', default=get_default_company)

    @api.depends('ebiz_profile_id')
    def compute_company(self):
        self.company_ids = self.env.context.get('allowed_company_ids')

    @api.depends('ebiz_profile_id')
    def _compute_logs_line(self):
        for rec in self:
            rec.logs_line = self.env['logs.of.products'].search(rec._get_logs_domain())

    def action_open_upload_products(self):
        rec = self.env['upload.products'].create({})
        rec.create_default_records()
        return {
            'name': _('Upload Products'),
            'type': 'ir.actions.act_window',
            'res_model': 'upload.products',
            'res_id': rec.id,
            'view_id': self.env.ref('payment_ebizcharge_crm.form_view_action_upload_products', False).id,
            'view_mode': 'form',
            'target': 'inline',
        }

    def create_default_records(self):
        profile_obj = self.env['ebizcharge.instance.config']
        profile = profile_obj.get_upload_instance(active_model='upload.products', active_id=self)
        if profile:
            self.ebiz_profile_id = profile
        product_obj = self.env['product.template']
        # ebiz_product_internal_id is set once a product has been synced; those belong in Logs, not List.
        if self.ebiz_profile_id == '0':
            all_profiles = profile_obj.search(
                [('is_valid_credential', '=', True), ('is_active', '=', True), '|', ('company_ids', '=', False),
                 ('company_ids', 'in', self.env.context.get('allowed_company_ids'))])
            list_of_upload_products = product_obj.search(
                [('ebiz_profile_id', 'in', all_profiles.ids), ('ebiz_product_internal_id', '=', False)])
        else:
            list_of_upload_products = product_obj.search(
                [('ebiz_profile_id', '=', int(self.ebiz_profile_id)), ('ebiz_product_internal_id', '=', False)])

        self.transaction_history_line = [fields.Command.clear()] + [
            fields.Command.create({
                'product_name': product.id,
                'sync_transaction_id': self.id,
            })
            for product in list_of_upload_products
        ]


class ListOfProducts(models.Model):
    _name = 'list.of.products'
    _description = "List of Products"
    _order = 'create_date desc'

    sync_transaction_id = fields.Many2one('upload.products', string='Product Reference', required=True,
                                          ondelete='cascade', index=True, copy=False)
    name = fields.Char(string='Number')
    product_name = fields.Many2one('product.template', string='Name')
    product_id = fields.Integer(string='Product ID', related='product_name.id')
    internal_reference = fields.Char(string='Internal Reference', related='product_name.default_code')
    sales_price = fields.Float(string='Sales Price', related='product_name.list_price')
    cost = fields.Float('Cost', related='product_name.standard_price')
    quantity = fields.Float('Quantity On Hand', related='product_name.qty_available')
    type = fields.Selection(string='Product Type', related='product_name.type')
    ebiz_product_id = fields.Char('EBiz Product Internal ID', related='product_name.ebiz_product_internal_id')
    sync_status = fields.Char(string='Sync Status', related='product_name.sync_status')
    last_sync_date = fields.Datetime(string="Upload Date & Time", related='product_name.last_sync_date')
    currency_id = fields.Many2one('res.currency', 'Currency',
                                  default=lambda self: self.env.user.company_id.currency_id.id, required=True)

    def upload_products(self):
        if not self:
            raise UserError('Please select a record first!')
        action = self.mapped('product_name').add_update_to_ebiz(from_upload=True)
        self.filtered(lambda r: r.product_name.ebiz_product_internal_id).unlink()
        return action

    def export_products(self):
        if not self:
            raise UserError('Please select a record first!')
        column_names = ['Product', 'Internal Reference', 'Sales Price', 'Cost', 'Quantity On Hand', 'Type',
                        'Upload Date & Time', 'Upload Status']
        worksheet, workbook, header_style, text_center = self.env['ebizcharge.instance.config'].export_generic_method(
            sheet_name='Products', columns=column_names)
        i = 4
        for record in self:
            worksheet[0].write(i, 1, record.product_name.name or '', text_center)
            worksheet[0].write(i, 2, record.internal_reference or '', text_center)
            worksheet[0].write(i, 3, record.sales_price or '', text_center)
            worksheet[0].write(i, 4, record.cost or 0, text_center)
            worksheet[0].write(i, 5, record.quantity or 0, text_center)
            worksheet[0].write(i, 6, record.type or '', text_center)
            worksheet[0].write(i, 7, str(record.last_sync_date) if record.last_sync_date else '', text_center)
            worksheet[0].write(i, 8, record.sync_status or '', text_center)
            i += 1
        fp = BytesIO()
        workbook.save(fp)
        export_id = self.env['bill.excel'].create(
            {'excel_file': base64.encodebytes(fp.getvalue()), 'file_name': 'Products.xls'})
        return {
            'type': 'ir.actions.act_url',
            'url': f'web/content/?model=bill.excel&field=excel_file&download=true&id={export_id.id}&filename=Products.xls',
            'target': 'new',
        }


class LogsOfProducts(models.Model):
    _name = 'logs.of.products'
    _description = "Logs of Products"
    _order = 'last_sync_date desc'

    sync_log_id = fields.Many2one('upload.products', string='Product Reference',
                                  ondelete='cascade', index=True, copy=False)
    name = fields.Char(string='Name')
    product_name = fields.Many2one('product.template', string='Product Name')
    product_id = fields.Integer(string='Product ID', related='product_name.id')
    sales_price = fields.Float(string='Sales Price')
    cost = fields.Float('Cost')
    internal_reference = fields.Char(string='Internal Reference')
    quantity = fields.Float('Quantity On Hand')
    type = fields.Selection([('consu', 'Consumable'), ('service', 'Service'), ('product', 'Storable Product')],
                            'Product Type')
    sync_status = fields.Char(string='Sync Status')
    last_sync_date = fields.Datetime(string="Upload Date & Time")
    currency_id = fields.Many2one('res.currency', 'Currency',
                                  default=lambda self: self.env.user.company_id.currency_id.id, required=True)
    user_id = fields.Many2one('res.users', 'User')

    def export_logs(self):
        if not self:
            raise UserError('Please select a record first!')
        column_names = ['Product', 'Internal Reference', 'Sales Price', 'Cost', 'Quantity On Hand', 'Type',
                        'Upload Date & Time', 'Upload Status']
        worksheet, workbook, header_style, text_center = self.env['ebizcharge.instance.config'].export_generic_method(
            sheet_name='Products Logs', columns=column_names)
        i = 4
        for record in self:
            worksheet[0].write(i, 1, record.product_name.name or '', text_center)
            worksheet[0].write(i, 2, record.internal_reference or '', text_center)
            worksheet[0].write(i, 3, record.sales_price or '', text_center)
            worksheet[0].write(i, 4, record.cost or 0, text_center)
            worksheet[0].write(i, 5, record.quantity or 0, text_center)
            worksheet[0].write(i, 6, record.type or '', text_center)
            worksheet[0].write(i, 7, str(record.last_sync_date) if record.last_sync_date else '', text_center)
            worksheet[0].write(i, 8, record.sync_status or '', text_center)
            i += 1
        fp = BytesIO()
        workbook.save(fp)
        export_id = self.env['bill.excel'].create(
            {'excel_file': base64.encodebytes(fp.getvalue()), 'file_name': 'Products Logs.xls'})
        return {
            'type': 'ir.actions.act_url',
            'url': f'web/content/?model=bill.excel&field=excel_file&download=true&id={export_id.id}&filename=Products Logs.xls',
            'target': 'new',
        }

    def clear_logs(self):
        if not self:
            raise UserError('Please select a record first!')
        text = f"Are you sure you want to clear {len(self)} product(s) from the Log?"
        wizard = self.env['wizard.delete.upload.logs'].create({
            "record_id": self[0].sync_log_id.id or 0,
            "record_model": 'product',
            "text": text,
        })
        action = self.env.ref('payment_ebizcharge_crm.wizard_delete_upload_logs').read()[0]
        action['res_id'] = wizard.id
        action['context'] = dict(
            self.env.context,
            list_of_records=self.ids,
            model='logs.of.products',
        )
        return action
