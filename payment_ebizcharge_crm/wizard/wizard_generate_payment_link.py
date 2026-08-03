from odoo import fields, models, api
import logging
from ..models.ebiz_charge import message_wizard
from odoo.exceptions import ValidationError, UserError
from markupsafe import Markup
_logger = logging.getLogger(__name__)


class GeneratePaymentLinkWizard(models.TransientModel):
    _name = 'wizard.ebiz.generate.link.payment.bulk'
    _description = "EBiz Generate Payment Link Bulk"

    payment_lines = fields.One2many('ebiz.generate.payment.link.lines.bulk', 'wizard_id')
    ebiz_profile_id = fields.Many2one('ebizcharge.instance.config', string='EBizCharge Merchant Account')
    is_surch_enable = fields.Boolean(string='Surcharge Enabled', related='ebiz_profile_id.is_surcharge_enabled')
    merchant_toggle_sur_per_txn = fields.Boolean(related='ebiz_profile_id.merchant_toggle_sur_per_txn')
    invoice_link = fields.Boolean(string='Invoice link')
    sale_link = fields.Boolean(string='Sale link')

    def invalidate_existing_payment_link(self, record, instance):
        if record.save_payment_link:
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
            ebiz.client.service.DeleteEbizWebFormPayment(**{
                'securityToken': ebiz._generate_security_json(),
                'paymentInternalId': record.payment_internal_id,
            })
            if not record.is_email_request:
                record.message_post(
                    body=Markup(
                        'EBizCharge Payment Link invalidated: <a href="%s" target="_blank">%s</a>' % (
                            record.save_payment_link, record.save_payment_link)
                    ),
                    message_type="comment",
                )
            record.write({'save_payment_link': False})

    def generate_payment_link(self):
        try:
            wizards = []
            default_ebiz_model = 'account.move'
            if self.sale_link:
                default_ebiz_model = 'sale.order'
            for record in self.payment_lines:
                template_type_id = 'WebFormEmail' if default_ebiz_model == 'account.move' else 'SalesOrderWebFormEmail'
                tem_check = self.env['email.templates'].search([
                    ('template_type_id', '=', template_type_id),
                    ('instance_id', '=', record.customer_name.ebiz_profile_id.id)], limit=1)
                wizard_vals = {
                    'ebiz_profile_id': record.customer_name.ebiz_profile_id.id,
                    'partner_id': record.customer_name.id,
                    'amount': record.amount_residual_signed,
                    'currency_id': record.currency_id.id,
                    'res_model': 'account.move',
                    'link_check_box': True,
                    'select_template': tem_check.id,
                    'enable_surcharge': record.enable_surcharge,
                }
                wizard = self.env['ebiz.payment.link.wizard'].create(wizard_vals)
                wizards.append(wizard)
                if record.invoice_id:
                    self.invalidate_existing_payment_link(record.invoice_id, record.invoice_id.partner_id.ebiz_profile_id)
                    record.invoice_id.write({'inv_enable_sur': record.enable_surcharge})

                wizard.with_context(
                    {'active_model': default_ebiz_model, 'active_id': record.invoice_id.id,
                     'from_bulk': True, 'requested_amount': record.request_amount}).generate_link()
            # When launched from the bulk view, ask the final success popup to
            # rebuild the parent's bulk lines (via regenerate_line_ids in
            # message.wizard.action_confirm) so the surcharge change is reflected
            # without a manual refresh. Other callers omit the context key.
            bulk_regenerate_kwargs = {}
            if self.env.context.get('bulk_active_model') and self.env.context.get('bulk_active_id'):
                bulk_regenerate_kwargs = {
                    'bulk_regenerate_model': self.env.context.get('bulk_active_model'),
                    'bulk_regenerate_id': self.env.context.get('bulk_active_id'),
                }
            if self.invoice_link or self.sale_link:
                copy_links = []
                for record in self.payment_lines:
                    doc = record.invoice_id
                    if doc:
                        copy_link = {
                            'number': doc.name,
                            'link': doc.save_payment_link,
                        }
                        copy_links.append(fields.Command.create(copy_link))
                cpyline = {'copy_link_lines': copy_links}
                wiz = self.env['ebiz.payment.link.copy'].create(cpyline)
                action = self.env.ref('payment_ebizcharge_crm.wizard_copy_link_form_views_action').read()[0]
                action['res_id'] = wiz.id
                action['context'] = self.env.context
                return action
            return message_wizard(
                f'{len(wizards)} payment link(s) generated successfully.',
                **bulk_regenerate_kwargs,
            )
        except Exception as e:
            raise ValidationError(e)


class GeneratePaymentLinkLines(models.TransientModel):
    _name = 'ebiz.generate.payment.link.lines.bulk'
    _description = "EBiz Payment Lines Bulk"

    wizard_id = fields.Many2one('wizard.ebiz.generate.link.payment.bulk')
    name = fields.Char(string='Number')
    customer_name = fields.Many2one('res.partner', string='Customer')
    odoo_payment_link = fields.Boolean(string='Generated Link', )
    amount_residual_signed = fields.Float(string='Balance Remaining')
    amount_total_signed = fields.Float(string='Amount Total')
    request_amount = fields.Float(string='Request Amount', )
    amount_due = fields.Float(string='Amount Due')
    check_box = fields.Boolean('Select')
    link_check_box = fields.Boolean('Link Check Box')
    email_id = fields.Char(string='Email ID')
    invoice_id = fields.Many2one('account.move', 'Invoice')
    currency_id = fields.Many2one('res.currency', string='Company Currency')
    select_template = fields.Many2one('email.templates', string='Select Template')
    email_subject = fields.Char(string='Subject', related='select_template.template_subject')
    ebiz_profile_id = fields.Many2one('ebizcharge.instance.config')
    enable_surcharge = fields.Boolean(string='Enable Surcharge', default=True,
                                      help='When enabled, a surcharge fee will be added to all eligible payments processed with a credit card.')

    @api.constrains('request_amount')
    def _constrains_min_amount(self):
        for rec in self:
            if rec.request_amount > rec.amount_residual_signed:
                raise UserError('Request Amount cannot be greater than the Balance Remaining.')
            elif rec.request_amount < 0:
                raise UserError('Request Amount cannot be negative.')


class WizardRemoveExistPaymentLink(models.TransientModel):
    _name = 'wizard.exist.payment.link'
    _description = "Wizard Exist Payment Link"

    record_id = fields.Integer('Record Id')
    invoice_id = fields.Many2one('account.move', 'Invoice')
    record_model = fields.Char('Record Model')
    text = fields.Text('Message', readonly=True)

    def delete_record_link(self):
        line_ids = self.env.context.get('selected_line_ids', [])
        lines = self.env['inv.payment.link.bulk.line'].browse(line_ids).filtered('generated_link')
        bulk_regenerate_kwargs = {}
        if lines:
            bulk_regenerate_kwargs = {
                'bulk_regenerate_model': 'inv.payment.link.bulk',
                'bulk_regenerate_id': lines.sync_invoice_id.id,
            }
        for line in lines:
            line.invoice.delete_ebiz_invoice()
        return message_wizard(f'{len(lines)} payment link(s) removed successfully.', **bulk_regenerate_kwargs)


class WizardGenerateSelectPaymentLink(models.TransientModel):
    _name = 'wizard.generate.select.payment.link'
    _description = "Wizard Generate Select Payment Link"

    record_id = fields.Integer('Record Id')
    invoice_id = fields.Many2one('account.move', 'Invoice')
    record_model = fields.Char('Record Model')
    text = fields.Text('Message', readonly=True)

    def generate_selected_record_link(self):
        line_ids = self.env.context.get('selected_line_ids', [])
        lines = self.env['inv.payment.link.bulk.line'].browse(line_ids).filtered(lambda r: not r.generated_link)
        return lines._generate_payment_links()
