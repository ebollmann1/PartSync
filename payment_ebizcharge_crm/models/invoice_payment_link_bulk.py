# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging
from io import BytesIO
import base64
from .ebiz_charge import message_wizard
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)


class InvoicePaymentLinkBulk(models.Model):
    _name = 'inv.payment.link.bulk'
    _description = "Invoice Payment Link Bulk"

    def _default_get_start(self):
        return self.env['ebizcharge.instance.config'].get_document_download_start_date()

    def _default_get_end_date(self):
        today = datetime.now() + timedelta(days=1)
        return today.date()

    def get_default_company(self):
        company_ids = self.env.context.get('allowed_company_ids') or []
        instances = self.env['ebizcharge.instance.config'].search([
            ('is_active', '=', True), '|',
            ('company_ids', '=', False),
            ('company_ids', 'in', company_ids),
        ])
        return instances.company_ids.ids

    name = fields.Char(string='Generate Payment Links for Invoices', default="Generate Payment Links for Invoices")
    partner_id = fields.Many2one('res.partner', string='Select Customer', domain="[('ebiz_internal_id', '!=', False), "
                                                                                 "('ebiz_profile_id', '=', "
                                                                                 "ebiz_profile_id)]")
    invoice_lines = fields.One2many('inv.payment.link.bulk.line', 'sync_invoice_id', copy=True)
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
    company_ids = fields.Many2many('res.company', compute='compute_company', default=get_default_company)

    @api.depends('ebiz_profile_id')
    def compute_company(self):
        self.company_ids = self.env.context.get('allowed_company_ids')

    def action_open_generate_payment_links(self):
        profile = int(self.env['ebizcharge.instance.config'].get_upload_instance(active_model='inv.payment.link.bulk', active_id=self))
        record = self
        if profile:
            profile_rec = self.env['ebizcharge.instance.config'].browse(profile)
            record = self.create({
                'ebiz_profile_id': profile,
                'start_date': profile_rec._default_get_start(),
                'end_date': profile_rec._default_get_end_date(),
            })
            record.regenerate_line_ids()
        return {
            'name': _('Generate Payment Links for Invoices'),
            'type': 'ir.actions.act_window',
            'res_model': 'inv.payment.link.bulk',
            'res_id': record.id,
            'view_id': self.env.ref('payment_ebizcharge_crm.form_view_inv_payment_link_bulk', False).id,
            'view_mode': 'form',
            'target': 'inline',
        }

    def _prepare_ebiz_profile(self):
        profile = int(self.env['ebizcharge.instance.config'].get_upload_instance(active_model='inv.payment.link.bulk', active_id=self))
        if profile:
            self.ebiz_profile_id = profile
            self.start_date = self.ebiz_profile_id._default_get_start()
            self.end_date = self.ebiz_profile_id._default_get_end_date()
            self.generated_link_status = 'both_generated_and_not_generated'

    def _prepare_invoice_filters(self):
        invoices_filters = [('payment_state', '!=', 'paid'),
                            ('state', '=', 'posted'),
                            ('ebiz_invoice_status', '!=', 'pending'),
                            ('amount_residual', '>', 0),
                            ('move_type', 'not in', ['out_refund', 'in_invoice'])]

        if self.generated_link_status == 'generated':
            invoices_filters.append(('save_payment_link', '!=', False))

        if self.generated_link_status == 'not_generated':
            invoices_filters.append(('save_payment_link', '=', False))

        if self.end_date:
            invoices_filters.append(('date', '<=', self.end_date))

        if self.start_date:
            invoices_filters.append(('date', '>=', self.start_date))

        if self.partner_id:
            invoices_filters.append(('partner_id', '=', self.partner_id.id))

        if self.ebiz_profile_id:
            invoices_filters.append(('partner_id.ebiz_profile_id', '=', self.ebiz_profile_id.id))

        if self.number:
            invoices_filters.append(('name', 'ilike', self.number))

        return invoices_filters

    def _prepare_values_for_default_record(self, invoice):
        values = {
            'invoice': invoice.id,
            'partner_id': invoice.partner_id.id,
            'customer_id': str(invoice.partner_id.id),
            "currency_id": self.env.user.currency_id.id,
            'sync_invoice_id': self.id,
        }
        if not invoice.save_payment_link:
            inv_enable_sur = self.enable_surcharge_for_all != 'disable'
            values['inv_enable_sur'] = inv_enable_sur
            invoice.inv_enable_sur = inv_enable_sur
        else:
            values['inv_enable_sur'] = invoice.inv_enable_sur
        return values

    def create_default_records(self):
        self.regenerate_line_ids()

    def regenerate_line_ids(self, enable_surcharge_for_all=None):
        self.is_surcharge_toggle_visible = self.merchant_toggle_sur_per_txn and self.is_surcharge_enabled
        self._create_records_for_gpl_invoices()

    def _create_records_for_gpl_invoices(self):
        try:
            if self.start_date and self.end_date and self.start_date > self.end_date:
                return message_wizard('From Date should be lower than the To date!', 'Invalid Date')
            list_of_trans = [fields.Command.clear()]
            if self.ebiz_profile_id:
                invoices = self.env['account.move'].search(self._prepare_invoice_filters())
                list_of_trans += [fields.Command.create(self._prepare_values_for_default_record(inv)) for inv in invoices]
            self.invoice_lines = list_of_trans
        except Exception as e:
            raise ValidationError(e)



class InvoicePaymentLinkBulkLine(models.Model):
    _name = 'inv.payment.link.bulk.line'
    _order = 'invoice asc'
    _description = "Sync Batch Processing"

    sync_invoice_id = fields.Many2one('inv.payment.link.bulk', string='Partner Reference', required=True,
                                      ondelete='cascade', index=True, copy=False)
    ebiz_profile_id = fields.Many2one('ebizcharge.instance.config', string='EBizCharge Profile',
                                      related = 'sync_invoice_id.ebiz_profile_id')
    is_surcharge_enabled = fields.Boolean(related='sync_invoice_id.is_surcharge_enabled')
    merchant_toggle_sur_per_txn = fields.Boolean(related='sync_invoice_id.merchant_toggle_sur_per_txn')
    is_surcharge_toggle_visible = fields.Boolean(related='sync_invoice_id.is_surcharge_toggle_visible')
    inv_enable_sur = fields.Boolean(string='Surcharge')
    enable_surcharge_for_all = fields.Boolean(
        compute='_compute_enable_surcharge_for_all',
        inverse='_inverse_enable_surcharge_for_all',
    )
    invoice = fields.Many2one('account.move', string='Number')
    invoice_id = fields.Integer(string='Invoice ID', related='invoice.id')
    state = fields.Char(string='State')
    partner_id = fields.Many2one('res.partner', string='Customer')
    customer_id = fields.Char(string='Customer ID')
    amount_total_signed = fields.Monetary(string='Amount Total', related='invoice.amount_total')
    amount_residual_signed = fields.Monetary(string='Balance Remaining', related="invoice.amount_residual_signed")
    amount_untaxed = fields.Monetary(string='Tax Excluded', related='invoice.amount_untaxed_signed')
    generated_link = fields.Char(string='Generated Link', related='invoice.save_payment_link')
    odoo_payment_link = fields.Boolean(string='Odoo Generated Link', related='invoice.odoo_payment_link')
    currency_id = fields.Many2one("res.currency", string="Currency", readonly=True, required=True)
    invoice_date_due = fields.Date('Due Date', related='invoice.invoice_date_due')
    last_sync_date = fields.Datetime('Upload Date & Time', related='invoice.last_sync_date')
    sync_status = fields.Char('Sync Status', related='invoice.sync_response')
    invoice_date = fields.Date('Invoice Date', related='invoice.invoice_date')
    date_time = fields.Datetime(string='Date Time')
    amount = fields.Monetary(currency_field='currency_id')
    request_amount = fields.Float(string='Request Amount', compute='_compute_req_app_amount')

    @api.depends('inv_enable_sur')
    def _compute_enable_surcharge_for_all(self):
        for rec in self:
            rec.enable_surcharge_for_all = rec.inv_enable_sur

    def _inverse_enable_surcharge_for_all(self):
        for rec in self:
            # Don't update invoices that already have a generated payment link
            if rec.generated_link:
                continue
            rec.inv_enable_sur = rec.enable_surcharge_for_all
            if rec.invoice:
                rec.invoice.inv_enable_sur = rec.enable_surcharge_for_all

    def _compute_req_app_amount(self):
        for line in self:
            inv = line.invoice
            line.request_amount = (inv.request_amount if inv.request_amount > 0 else inv.amount_residual) if inv else 0

    @api.onchange('request_amount')
    def check_request_amount(self):
        for rec in self:
            if rec.request_amount > rec.amount_residual_signed:
                raise UserError('Request Amount cannot be greater than the Balance Remaining.')
            elif rec.request_amount < 0:
                raise UserError('Request Amount cannot be negative.')

    @api.depends('invoice.amount_residual')
    def compute_bal_amount(self):
        for rec in self:
            rec.amount_residual_signed = rec.invoice.amount_residual - rec.request_amount if rec.invoice.amount_residual > 0 else 0

    def write(self, vals):
        if 'inv_enable_sur' in vals:
            locked = self.filtered('generated_link')
            unlocked = self - locked
            result = super(InvoicePaymentLinkBulkLine, unlocked).write(vals) if unlocked else True
            if locked:
                other_vals = {k: v for k, v in vals.items() if k != 'inv_enable_sur'}
                if other_vals:
                    super(InvoicePaymentLinkBulkLine, locked).write(other_vals)
            for rec in unlocked:
                if rec.invoice:
                    rec.invoice.inv_enable_sur = vals['inv_enable_sur']
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
                wizard = self.env['wizard.generate.select.payment.link'].create({
                    "record_id": self[0].sync_invoice_id.id,
                    "record_model": 'inv.payment.link.bulk',
                    "text": text,
                })
                action = self.env.ref('payment_ebizcharge_crm.wizard_generate_select_payment_link_action').read()[0]
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
                inv = line.invoice
                payment_lines.append(fields.Command.create({
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
                    "enable_surcharge": inv.inv_enable_sur,
                }))
                profile = inv.partner_id.ebiz_profile_id.id
        wiz = self.env['wizard.ebiz.generate.link.payment.bulk'].with_context(
            profile=profile).create({'payment_lines': payment_lines, 'ebiz_profile_id': profile})
        action = self.env.ref('payment_ebizcharge_crm.wizard_generate_link_form_views_action').read()[0]
        action['res_id'] = wiz.id
        action['context'] = dict(self.env.context, bulk_active_model='inv.payment.link.bulk', bulk_active_id=self.sync_invoice_id.id)
        return action

    def action_remove_paylink(self):
        try:
            if not self:
                raise UserError('Please select a record first!')
            if not any(bool(rec.generated_link) for rec in self):
                raise UserError('A generated link does not exist.')
            text = ("Removing generated links will cancel existing payment links. A new link would need to be "
                    "generated again.\nAre you sure you want to continue?")
            wizard = self.env['wizard.exist.payment.link'].create({
                "record_id": self[0].sync_invoice_id.id,
                "record_model": 'inv.payment.link.bulk',
                "text": text,
            })
            action = self.env.ref('payment_ebizcharge_crm.wizard_exist_payment_link_action').read()[0]
            action['res_id'] = wizard.id
            action['context'] = dict(self.env.context, selected_line_ids=self.ids)
            return action
        except Exception as e:
            raise ValidationError(e)

    def export_invoices(self):
        if not self:
            raise UserError('Please select a record first!')
        column_names = ['Customer ID', 'Customer', 'Number', 'Invoice Date', 'Invoice Total', 'Balance Remaining',
                        'Request Amount', 'Generated Link']
        worksheet, workbook, header_style, text_center = self.env['ebizcharge.instance.config'].export_generic_method(
            sheet_name='Invoices', columns=column_names)
        i = 4
        for record in self:
            worksheet[0].write(i, 1, record.customer_id or '', text_center)
            worksheet[0].write(i, 2, record.partner_id.name or '', text_center)
            worksheet[0].write(i, 3, record.invoice.name or '', text_center)
            worksheet[0].write(i, 4, str(record.invoice_date) or '', text_center)
            worksheet[0].write(i, 5, record.amount_total_signed or '', text_center)
            worksheet[0].write(i, 6, record.amount_residual_signed or 0, text_center)
            worksheet[0].write(i, 7, record.request_amount or 0, text_center)
            worksheet[0].write(i, 8, record.generated_link or '', text_center)
            i += 1
        fp = BytesIO()
        workbook.save(fp)
        export_id = self.env['bill.excel'].create(
            {'excel_file': base64.encodebytes(fp.getvalue()), 'file_name': 'Generate_Payment_Link.xls'})
        return {
            'type': 'ir.actions.act_url',
            'url': f'web/content/?model=bill.excel&field=excel_file&download=true&id={export_id.id}&filename=Generate_Payment_Link.xls',
            'target': 'new',
        }

