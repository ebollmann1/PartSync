# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging
from .ebiz_charge import message_wizard
from io import BytesIO
import base64
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)


class SaleOrderPaymentLinkBulk(models.Model):
    _name = 'sale.order.payment.link.bulk'
    _description = "Sale Order Payment Link Bulk"

    def _default_get_start(self):
        return self.env['ebizcharge.instance.config'].get_document_download_start_date()

    def _default_get_end_date(self):
        today = datetime.now() + timedelta(days=1)
        return today.date()

    def get_default_company(self):
        return self.env['ebizcharge.instance.config'].search(
            [('is_active', '=', True), '|', ('company_ids', '=', False),
             ('company_ids', 'in', self.env.context.get('allowed_company_ids'))]).company_ids.ids

    name = fields.Char(string='Generate Payment Links for Sales Orders', default="Generate Payment Links for Sales Orders")
    company_ids = fields.Many2many('res.company', compute='compute_company', default=get_default_company)
    partner_id = fields.Many2one('res.partner', string='Select Customer', domain="[('ebiz_internal_id', '!=', False), "
                                                                                 "('ebiz_profile_id', '=', "
                                                                                 "ebiz_profile_id)]")
    sale_order_lines = fields.One2many('sale.order.payment.link.bulk.line', 'sync_order_id', copy=True)
    add_filter = fields.Boolean(string='Filters')
    number = fields.Char(string='Number')
    generated_link_status = fields.Selection(
        [('both_generated_and_not_generated', 'Both Generated & Not Generated'), ('generated', 'Generated'),
         ('not_generated', 'Not Generated')],
        string='Generated Link Status', required=True, default='both_generated_and_not_generated')
    start_date = fields.Date(string='From Date')
    end_date = fields.Date(string='To Date')
    ebiz_profile_id = fields.Many2one('ebizcharge.instance.config', string='EBizCharge Profile')
    merchant_toggle_sur_per_txn = fields.Boolean(related='ebiz_profile_id.merchant_toggle_sur_per_txn')
    is_surcharge_enabled = fields.Boolean(related='ebiz_profile_id.is_surcharge_enabled')
    is_surcharge_toggle_visible = fields.Boolean(default=False)
    is_reopened = fields.Boolean(default=False)
    enable_surcharge_for_all = fields.Selection([('none', 'None'), ('enable', 'Enable'), ('disable', 'Disable')],
                                                default='enable')

    @api.depends('ebiz_profile_id')
    def compute_company(self):
        self.company_ids = self.env.context.get('allowed_company_ids')

    def action_open_generate_payment_links_so(self):
        profile_obj = self.env['ebizcharge.instance.config']
        profile = int(profile_obj.get_upload_instance(active_model='sale.order.payment.link.bulk', active_id=self))
        record = self
        if profile:
            ebiz_profile_id = self.env['ebizcharge.instance.config'].browse(profile)
            record = self.create({
                'ebiz_profile_id': profile,
                'start_date': ebiz_profile_id._default_get_start(),
                'end_date': ebiz_profile_id._default_get_end_date(),
            })
            record.regenerate_line_ids()
        return {
            'name': _('Generate Payment Links for Sales Orders'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.payment.link.bulk',
            'res_id': record.id,
            'view_id': self.env.ref('payment_ebizcharge_crm.form_view_sale_order_payment_link_bulk', False).id,
            'view_mode': 'form',
            'target': 'inline',
        }

    def _prepare_values_for_default_record(self, order, transaction_type):
        values = {
            'order_id': order.id,
            'transaction_type': transaction_type,
            'partner_id': order.partner_id.id,
            'customer_id': order.partner_id.id,
            "currency_id": self.env.user.currency_id.id,
            'sync_order_id': self.id,
        }
        if not order.save_payment_link:
            sale_enable_sur = self.enable_surcharge_for_all != 'disable'
            values['sale_enable_sur'] = sale_enable_sur
            order.sale_enable_sur = sale_enable_sur
        else:
            values['sale_enable_sur'] = order.sale_enable_sur
        return values

    def _prepare_order_filters(self):
        order_filters = [('invoice_status', '!=', 'invoiced'), ('state', '!=', 'cancel'),
                         ('website_id', '=', False)]

        if self.number:
            order_filters.append(('name', 'ilike', self.number))

        if self.generated_link_status == 'generated':
            order_filters.append(('save_payment_link', '!=', False))

        if self.generated_link_status == 'not_generated':
            order_filters.append(('save_payment_link', '=', False))

        if self.end_date:
            order_filters.append(('date_order', '<=', self.end_date))

        if self.start_date:
            order_filters.append(('date_order', '>=', self.start_date))

        if self.partner_id:
            order_filters.append(('partner_id', '=', self.partner_id.id))

        if self.ebiz_profile_id:
            order_filters.append(('partner_id.ebiz_profile_id', '=', self.ebiz_profile_id.id))

        return order_filters

    def create_default_records(self):
        self.regenerate_line_ids()

    def regenerate_line_ids(self, enable_surcharge_for_all=None):
        self.is_surcharge_toggle_visible = self.merchant_toggle_sur_per_txn and self.is_surcharge_enabled
        self._create_records_for_gpl_sales_orders()

    def _create_records_for_gpl_sales_orders(self):
        try:
            list_of_trans = []
            self.sale_order_lines.unlink()
            if self.start_date and self.end_date:
                if self.start_date > self.end_date:
                    return message_wizard('From Date should be lower than the To date!', 'Invalid Date')
            if self.ebiz_profile_id:
                order_filters = self._prepare_order_filters()
                sale_orders = self.env['sale.order'].search(order_filters)

                for order in sale_orders:
                    if order.ebiz_order_amount_residual > 0.0:
                        transaction_type = (order.save_payment_link and order.transaction_type) or self.ebiz_profile_id.gpl_pay_sale
                        values = self._prepare_values_for_default_record(order, transaction_type)
                        list_of_trans.append(values)
            self.env['sale.order.payment.link.bulk.line'].create(list_of_trans)
        except Exception as e:
            raise ValidationError(e)


class SaleOrderPaymentLinkBulkLine(models.Model):
    _name = 'sale.order.payment.link.bulk.line'
    _order = 'order_id asc'
    _description = "Sale Order Payment Link Bulk Line"

    sync_order_id = fields.Many2one('sale.order.payment.link.bulk', string='Partner Reference',
                                    ondelete='cascade', index=True, copy=False)
    ebiz_profile_id = fields.Many2one('ebizcharge.instance.config', string='EBizCharge Profile',
                                      related='sync_order_id.ebiz_profile_id')
    is_surcharge_enabled = fields.Boolean(related='sync_order_id.is_surcharge_enabled')
    merchant_toggle_sur_per_txn = fields.Boolean(related='sync_order_id.merchant_toggle_sur_per_txn')
    is_surcharge_toggle_visible = fields.Boolean(related='sync_order_id.is_surcharge_toggle_visible')
    sale_enable_sur = fields.Boolean(string='Surcharge')
    # inv_enable_sur: alias required because the widget payload hardcodes this field name
    inv_enable_sur = fields.Boolean(
        compute='_compute_inv_enable_sur',
        inverse='_inverse_inv_enable_sur',
    )
    enable_surcharge_for_all = fields.Boolean(
        compute='_compute_enable_surcharge_for_all',
        inverse='_inverse_enable_surcharge_for_all',
    )
    order_id = fields.Many2one('sale.order', string='Number')
    customer_id = fields.Char(string='Customer ID')
    partner_id = fields.Many2one('res.partner', string='Customer')
    amount_total_signed = fields.Monetary(string='Amount Total', related='order_id.amount_total')
    currency_id = fields.Many2one("res.currency", string="Currency", readonly=True)
    date_order = fields.Datetime('Quotation Date', related='order_id.date_order')
    transaction_type = fields.Selection(
        [('pre_auth', 'Pre-Auth'), ('deposit', 'Deposit')],
        string='Transaction Type')
    date_time = fields.Datetime(string='Date Time')
    generated_link = fields.Char(string='Generated Link', related='order_id.save_payment_link')
    so_payment_link = fields.Boolean(string='Generated Links', related='order_id.odoo_payment_link')
    request_amount = fields.Float(string='Request Amount')
    amount_residual_signed = fields.Float(string='Balance Remaining', compute='compute_bal_amount')

    @api.depends('sale_enable_sur')
    def _compute_inv_enable_sur(self):
        for rec in self:
            rec.inv_enable_sur = rec.sale_enable_sur

    def _inverse_inv_enable_sur(self):
        for rec in self:
            rec.sale_enable_sur = rec.inv_enable_sur

    @api.depends('sale_enable_sur')
    def _compute_enable_surcharge_for_all(self):
        for rec in self:
            rec.enable_surcharge_for_all = rec.sale_enable_sur

    def _inverse_enable_surcharge_for_all(self):
        for rec in self:
            if rec.generated_link:
                continue
            rec.sale_enable_sur = rec.enable_surcharge_for_all
            if rec.order_id:
                rec.order_id.sale_enable_sur = rec.enable_surcharge_for_all

    @api.depends('order_id.ebiz_amount_residual', 'order_id.invoice_status')
    def compute_bal_amount(self):
        for rec in self:
            rec.amount_residual_signed = rec.order_id.ebiz_order_amount_residual if rec.order_id.invoice_status != 'invoiced' else 0
            rec.request_amount = rec.order_id.request_amount if rec.order_id.request_amount > 0.0 else rec.order_id.ebiz_order_amount_residual

    def write(self, vals):
        if 'sale_enable_sur' in vals:
            locked = self.filtered('generated_link')
            unlocked = self - locked
            result = super(SaleOrderPaymentLinkBulkLine, unlocked).write(vals) if unlocked else True
            if locked:
                other_vals = {k: v for k, v in vals.items() if k != 'sale_enable_sur'}
                if other_vals:
                    super(SaleOrderPaymentLinkBulkLine, locked).write(other_vals)
            for rec in unlocked:
                if rec.order_id:
                    rec.order_id.sale_enable_sur = vals['sale_enable_sur']
            return result
        return super().write(vals)

    def action_generate_payment_link(self):
        try:
            if not self:
                raise UserError('Please select a record first!')
            if all(bool(rec.generated_link) for rec in self):
                raise UserError('A generated link already exists.')
            if any(bool(rec.generated_link) for rec in self):
                text = ("Links will only be generated for selected records without existing links. "
                        "Are you sure you want to continue?")
                wizard = self.env['wizard.generate.so.select.payment.link'].create({
                    "record_id": self[0].sync_order_id.id,
                    "record_model": 'sale.order.payment.link.bulk',
                    "text": text,
                })
                action = self.env.ref('payment_ebizcharge_crm.wizard_generate_so_select_payment_link_action').read()[0]
                action['res_id'] = wizard.id
                action['context'] = dict(self.env.context, selected_line_ids=self.ids)
                return action
            return self._generate_payment_links()
        except Exception as e:
            raise ValidationError(e)

    def _generate_payment_links(self):
        payment_lines = []
        profile = False
        for line in self:
            if not line.generated_link:
                so = line.order_id
                payment_lines.append(fields.Command.create({
                    "order_id": so.id,
                    "partner_id": so.partner_id.id,
                    "transaction_type": line.transaction_type,
                    "amount_total_signed": so.amount_total,
                    "request_amount": so.ebiz_order_amount_residual,
                    "so_payment_link": so.odoo_payment_link,
                    "currency_id": self.env.user.currency_id.id,
                    "email_id": so.partner_id.email,
                    "ebiz_profile_id": so.partner_id.ebiz_profile_id.id,
                    "enable_surcharge": so.sale_enable_sur,
                }))
                profile = so.partner_id.ebiz_profile_id.id
        wiz = self.env['wizard.generate.so.link.payment'].with_context(
            profile=profile).create({'payment_lines': payment_lines, 'ebiz_profile_id': profile})
        action = self.env.ref('payment_ebizcharge_crm.wizard_generate_so_link_form_views_action').read()[0]
        action['res_id'] = wiz.id
        action['context'] = dict(self.env.context, bulk_active_model='sale.order.payment.link.bulk', bulk_active_id=self.sync_order_id.id)
        return action

    def action_remove_payment_link(self):
        try:
            if not self:
                raise UserError('Please select a record first!')
            if not any(bool(rec.generated_link) for rec in self):
                raise UserError('A generated link does not exist.')
            text = ("Removing generated links will cancel existing payment links. A new link would need to be "
                    "generated again.\nAre you sure you want to continue?")
            wizard = self.env['wizard.so.exist.payment.link'].create({
                "record_model": 'sale.order.payment.link.bulk',
                "text": text,
            })
            action = self.env.ref('payment_ebizcharge_crm.wizard_so_exist_payment_link_action').read()[0]
            action['res_id'] = wizard.id
            action['context'] = dict(self.env.context, selected_line_ids=self.ids)
            return action
        except Exception as e:
            raise ValidationError(e)

    def export_sale_order(self):
        if not self:
            raise UserError('Please select a record first!')
        column_names = ['Customer ID', 'Customer', 'Number', 'Order Date', 'Order Total', 'Balance Remaining',
                        'Request Amount', 'Generated Link']
        worksheet, workbook, header_style, text_center = self.env['ebizcharge.instance.config'].export_generic_method(
            sheet_name='Sale Orders', columns=column_names)
        i = 4
        for record in self:
            worksheet[0].write(i, 1, record.partner_id.id or '', text_center)
            worksheet[0].write(i, 2, record.partner_id.name or '', text_center)
            worksheet[0].write(i, 3, record.order_id.name or '', text_center)
            worksheet[0].write(i, 4, str(record.date_order) or '', text_center)
            worksheet[0].write(i, 5, record.amount_total_signed or '', text_center)
            worksheet[0].write(i, 6, record.amount_residual_signed or 0, text_center)
            worksheet[0].write(i, 7, record.request_amount or 0, text_center)
            worksheet[0].write(i, 8, record.generated_link or '', text_center)
            i += 1
        fp = BytesIO()
        workbook.save(fp)
        export_id = self.env['bill.excel'].create(
            {'excel_file': base64.encodebytes(fp.getvalue()), 'file_name': 'Generate_Sale_Payment_Link.xls'})
        return {
            'type': 'ir.actions.act_url',
            'url': f'web/content/?model=bill.excel&field=excel_file&download=true&id={export_id.id}&filename=Generate_Sale_Payment_Link.xls',
            'target': 'new',
        }
