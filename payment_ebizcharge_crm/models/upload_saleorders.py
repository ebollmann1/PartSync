# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
from io import BytesIO
import base64

_logger = logging.getLogger(__name__)


class UploadSaleOrders(models.Model):
    _name = 'upload.sale.orders'
    _description = "Upload Sale Orders"

    def get_default_company(self):
        companies = self.env['ebizcharge.instance.config'].search(
            [('is_active', '=', True), '|', ('company_ids', '=', False), (
                'company_ids', 'in', self.env.context.get('allowed_company_ids'))]).mapped('company_ids').ids
        return companies

    @api.depends('ebiz_profile_id')
    def compute_company(self):
        self.company_ids = self.env.context.get('allowed_company_ids')

    def domain_users(self):
        return [('user_id', '=', self.env.user.id)]

    def _get_logs_domain(self):
        if self.ebiz_profile_id == '0':
            all_profiles = self.env['ebizcharge.instance.config'].search(
                [('is_valid_credential', '=', True), ('is_active', '=', True), '|', ('company_ids', '=', False),
                 ('company_ids', 'in', self.env.context.get('allowed_company_ids'))])
            instances = all_profiles.ids
        else:
            instances = [int(self.ebiz_profile_id)]
        return [('customer_id.ebiz_profile_id', 'in', instances)]

    def _get_all_instance(self):
        all_list = [("0", "All")]
        profiles = self.env['ebizcharge.instance.config'].search([('is_valid_credential', '=', True),
                                                                  ('is_active', '=', True), '|',
                                                                  ('company_ids', '=', False),
                                                                  ('company_ids', 'in', self.env.companies.ids)])
        instance = [(str(profile.id), profile.name) for profile in profiles]
        return all_list + instance

    company_ids = fields.Many2many('res.company', compute='compute_company', default=get_default_company)
    # Computed Many2many instead of a sync_log_id-backed One2many: logs are visible based on the
    # current ebiz_profile_id scope, independent of which upload.sale.orders parent created them.
    # This fixes the bug where logs were attached to whichever parent existed when sync_to_ebiz ran,
    # which left orphan logs invisible if no upload screen had been opened yet.
    logs_line = fields.Many2many('logs.of.orders', compute='_compute_logs_line')
    add_filter = fields.Boolean(string='Filters')
    name = fields.Char(default='Upload Sales Orders')
    transaction_history_line = fields.One2many('list.of.orders', 'sync_transaction_id', copy=True)
    ebiz_profile_id = fields.Selection(selection=_get_all_instance)

    @api.depends('ebiz_profile_id')
    def _compute_logs_line(self):
        for rec in self:
            rec.logs_line = self.env['logs.of.orders'].search(rec._get_logs_domain())

    def action_open_upload_sale_orders(self):
        rec = self.env['upload.sale.orders'].create({})
        rec.create_default_records()
        return {
            'name': _('Upload Sales Orders'),
            'type': 'ir.actions.act_window',
            'res_model': 'upload.sale.orders',
            'res_id': rec.id,
            'view_id': self.env.ref('payment_ebizcharge_crm.form_view_request_upload_sale_orders', False).id,
            'view_mode': 'form',
            'target': 'inline',
        }

    def create_default_records(self):
        profile_obj = self.env['ebizcharge.instance.config']
        profile = profile_obj.get_upload_instance(active_model='upload.sale.orders', active_id=self)
        if profile:
            self.ebiz_profile_id = profile
        sale_obj = self.env['sale.order']
        # ebiz_internal_id is set once an order has been synced to EBizCharge — those belong on the
        # Logs page (populated by create_odoo_logs), so the List page should only show pending orders.
        if self.ebiz_profile_id == '0':
            all_profiles = profile_obj.search(
                [('is_valid_credential', '=', True), ('is_active', '=', True), '|', ('company_ids', '=', False),
                 ('company_ids', 'in', self.env.context.get('allowed_company_ids'))])
            list_of_orders = sale_obj.search(
                [('partner_id.ebiz_profile_id', 'in', all_profiles.ids), ('ebiz_internal_id', '=', False)])
        else:
            list_of_orders = sale_obj.search(
                [('partner_id.ebiz_profile_id', '=', int(self.ebiz_profile_id)), ('ebiz_internal_id', '=', False)])

        self.transaction_history_line = [fields.Command.clear()] + [
            fields.Command.create({
                'order_no': order.id,
                'customer_id': order.partner_id.id,
                'currency_id': self.env.user.currency_id.id,
                'sync_transaction_id': self.id,
            })
            for order in list_of_orders
        ]


class ListOfOrders(models.Model):
    _name = 'list.of.orders'
    _order = 'create_date desc'
    _description = "List of Orders"

    sync_transaction_id = fields.Many2one('upload.sale.orders', string='Partner Reference', required=True,
                                          ondelete='cascade', index=True, copy=False)
    order_no = fields.Many2one('sale.order', string='Order No')
    order_id = fields.Integer(string='Order Number', related="order_no.id")
    customer_id = fields.Many2one('res.partner', string='Customer')
    amount_total = fields.Monetary(string='Order Total', related='order_no.amount_total')
    amount_due = fields.Monetary(string='Balance Remaining', related='order_no.amount_due_custom')
    currency_id = fields.Many2one("res.currency", string="Currency", readonly=True, required=True)
    order_date = fields.Datetime('Order Date', related='order_no.date_order')
    sync_status = fields.Char(string='Sync Status', related='order_no.sync_response')
    last_sync_date = fields.Datetime(string="Upload Date & Time", related='order_no.last_sync_date')

    def upload_sale_orders(self):
        if not self:
            raise UserError('Please select a record first!')
        action = self.mapped('order_no').sync_multi_sale_orders()
        self.filtered(lambda r: r.order_no.ebiz_internal_id).unlink()
        return action

    def export_orders(self):
        if not self:
            raise UserError('Please select a record first!')
        column_names = ['Order Number', 'Customer', 'Customer ID', 'Order Total', 'Balance Remaining',
                        'Order Date', 'Upload Date & Time', 'Upload Status']
        worksheet, workbook, header_style, text_center = self.env['ebizcharge.instance.config'].export_generic_method(
            sheet_name='Sales Orders', columns=column_names)
        i = 4
        for record in self:
            worksheet[0].write(i, 1, record.order_no.name or '', text_center)
            worksheet[0].write(i, 2, record.customer_id.name or '', text_center)
            worksheet[0].write(i, 3, str(record.customer_id.id) if record.customer_id else '', text_center)
            worksheet[0].write(i, 4, record.amount_total or '', text_center)
            worksheet[0].write(i, 5, record.amount_due or 0, text_center)
            worksheet[0].write(i, 6, str(record.order_date) or '', text_center)
            worksheet[0].write(i, 7, str(record.last_sync_date) or '', text_center)
            worksheet[0].write(i, 8, record.sync_status or '', text_center)
            i += 1
        fp = BytesIO()
        workbook.save(fp)
        export_id = self.env['bill.excel'].create(
            {'excel_file': base64.encodebytes(fp.getvalue()), 'file_name': 'Sales Orders.xls'})
        return {
            'type': 'ir.actions.act_url',
            'url': f'web/content/?model=bill.excel&field=excel_file&download=true&id={export_id.id}&filename=Sales Orders.xls',
            'target': 'new',
        }


class LogsOfOrders(models.Model):
    _name = 'logs.of.orders'
    _order = 'last_sync_date desc'
    _description = "Logs of Orders"

    sync_log_id = fields.Many2one('upload.sale.orders', string='Partner Reference',
                                  ondelete='cascade', index=True, copy=False)
    order_no = fields.Many2one('sale.order', string='Order Number')
    customer_id = fields.Many2one('res.partner', string='Customer')
    amount_total = fields.Monetary(string='Order Total')
    amount_due = fields.Monetary(string='Balance Remaining')
    currency_id = fields.Many2one("res.currency", string="Currency", readonly=True, required=True)
    order_date = fields.Datetime('Order Date')
    sync_status = fields.Char(string='Upload Status')
    last_sync_date = fields.Datetime(string="Upload Date & Time")
    user_id = fields.Many2one('res.users', 'User')

    def export_logs(self):
        if not self:
            raise UserError('Please select a record first!')
        column_names = ['Order Number', 'Customer', 'Customer ID', 'Order Total', 'Balance Remaining',
                        'Order Date', 'Upload Date & Time', 'Upload Status']
        worksheet, workbook, header_style, text_center = self.env['ebizcharge.instance.config'].export_generic_method(
            sheet_name='SalesOrders Logs', columns=column_names)
        i = 4
        for record in self:
            worksheet[0].write(i, 1, record.order_no.name or '', text_center)
            worksheet[0].write(i, 2, record.customer_id.name or '', text_center)
            worksheet[0].write(i, 3, str(record.customer_id.id) if record.customer_id else '', text_center)
            worksheet[0].write(i, 4, record.amount_total or '', text_center)
            worksheet[0].write(i, 5, record.amount_due or 0, text_center)
            worksheet[0].write(i, 6, str(record.order_date) or '', text_center)
            worksheet[0].write(i, 7, str(record.last_sync_date) or '', text_center)
            worksheet[0].write(i, 8, record.sync_status or '', text_center)
            i += 1
        fp = BytesIO()
        workbook.save(fp)
        export_id = self.env['bill.excel'].create(
            {'excel_file': base64.encodebytes(fp.getvalue()), 'file_name': 'SalesOrders Logs.xls'})
        return {
            'type': 'ir.actions.act_url',
            'url': f'web/content/?model=bill.excel&field=excel_file&download=true&id={export_id.id}&filename=SalesOrders Logs.xls',
            'target': 'new',
        }

    def clear_logs(self):
        if not self:
            raise UserError('Please select a record first!')
        text = f"Are you sure you want to clear {len(self)} sales order(s) from the Log?"
        wizard = self.env['wizard.delete.upload.logs'].create({
            "record_id": self[0].sync_log_id.id or 0,
            "record_model": 'sales order',
            "text": text,
        })
        action = self.env.ref('payment_ebizcharge_crm.wizard_delete_upload_logs').read()[0]
        action['res_id'] = wizard.id
        action['context'] = dict(
            self.env.context,
            list_of_records=self.ids,
            model='logs.of.orders',
        )
        return action
