from odoo import fields, models, api
import logging
from ..models.ebiz_charge import message_wizard
from odoo.exceptions import ValidationError, UserError
from markupsafe import Markup
_logger = logging.getLogger(__name__)


class WizardGenerateSoPaymentLink(models.TransientModel):
    _name = 'wizard.generate.so.link.payment'
    _description = "Wizard Generate So Payment Link"

    payment_lines = fields.One2many('wizard.generate.so.payment.link.lines', 'wizard_id')
    ebiz_profile_id = fields.Many2one('ebizcharge.instance.config', string='EBizCharge Merchant Account')
    sale_link = fields.Boolean(string='Sales')
    is_surch_enable = fields.Boolean(string='Surcharge Enabled', related='ebiz_profile_id.is_surcharge_enabled')
    merchant_toggle_sur_per_txn = fields.Boolean(related='ebiz_profile_id.merchant_toggle_sur_per_txn')

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
            if any(rec.transaction_type == 'pre_auth' and rec.request_amount < rec.amount_residual_signed for rec in self.payment_lines):
                raise UserError('Request Amount must be greater than or equal to Balance Remaining for Pre-Auths.')
            for record in self.payment_lines:
                tem_check = self.env['email.templates'].search([
                    ('template_type_id', '=', 'SalesOrderWebFormEmail'),
                    ('instance_id', '=', record.partner_id.ebiz_profile_id.id)], limit=1)
                wizard_vals = {
                    'ebiz_profile_id': record.partner_id.ebiz_profile_id.id,
                    'partner_id': record.partner_id.id,
                    'amount': record.amount_residual_signed,
                    'currency_id': record.currency_id.id,
                    'res_model': 'sale.order',
                    'link_check_box': True,
                    'select_template': tem_check.id,
                    'transaction_type': record.transaction_type,
                    'is_sale_order': True,
                    'enable_surcharge': record.enable_surcharge,
                }
                wizard = self.env['ebiz.payment.link.wizard'].create(wizard_vals)
                wizards.append(wizard)
                if record.order_id:
                    self.invalidate_existing_payment_link(record.order_id, record.order_id.partner_id.ebiz_profile_id)
                    record.order_id.write({'sale_enable_sur': record.enable_surcharge, 'transaction_type': record.transaction_type})

                wizard.with_context(
                    {'active_model': 'sale.order', 'active_id': record.order_id.id,
                     'from_bulk': True,
                     'requested_amount': record.request_amount}).generate_link()

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
            if self.sale_link:
                copy_links = []
                for record in self.payment_lines:
                    doc = record.order_id
                    if doc:
                        copy_link = {
                            'number': doc.name,
                            'link': doc.save_payment_link,
                        }
                        copy_links.append(fields.Command.create(copy_link))
                # raise UserError(str(copy_links))
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


class WizardGenerateSoPaymentLinkLines(models.TransientModel):
    _name = 'wizard.generate.so.payment.link.lines'
    _description = "Wizard Generate So Payment Link Lines"

    wizard_id = fields.Many2one('wizard.generate.so.link.payment')
    order_id = fields.Many2one('sale.order', 'So')
    name = fields.Char(string='Number')
    partner_id = fields.Many2one('res.partner', string='Customer')
    so_payment_link = fields.Boolean(string='Generated Link', )
    amount_residual_signed = fields.Float(string='Balance Remaining', related='order_id.ebiz_order_amount_residual')
    amount_total_signed = fields.Float(string='Amount Total')
    request_amount = fields.Float(string='Request Amount', )
    amount_due = fields.Float(string='Amount Due')
    check_box = fields.Boolean('Select')
    link_check_box = fields.Boolean('Link Check Box')
    email_id = fields.Char(string='Email ID')
    record_id = fields.Char('Invoice ID')
    currency_id = fields.Many2one('res.currency', string='Company Currency')
    select_template = fields.Many2one('email.templates', string='Select Template')
    email_subject = fields.Char(string='Subject', related='select_template.template_subject')
    ebiz_profile_id = fields.Many2one('ebizcharge.instance.config')
    transaction_type = fields.Selection([
        ('pre_auth', 'Pre-Auth'),
        ('deposit', 'Deposit'),
    ], string='Transaction Type', required=True, default='pre_auth')
    enable_surcharge = fields.Boolean(string='Enable Surcharge', default=True,
                                      help='When enabled, a surcharge fee will be added to all eligible payments processed with a credit card.')

class WizardRemoveSoExistPaymentLink(models.TransientModel):
    _name = 'wizard.so.exist.payment.link'
    _description = "Wizard SO Exist Payment Link"

    record_id = fields.Many2one('sale.order', 'SO')
    record_model = fields.Char('Record Model')
    text = fields.Text('Message', readonly=True)

    def delete_record_link(self):
        line_ids = self.env.context.get('selected_line_ids', [])
        lines = self.env['sale.order.payment.link.bulk.line'].browse(line_ids).filtered('generated_link')
        bulk_regenerate_kwargs = {}
        if lines:
            bulk_regenerate_kwargs = {
                'bulk_regenerate_model': 'sale.order.payment.link.bulk',
                'bulk_regenerate_id': lines.sync_order_id.id,
            }
        for line in lines:
            line.order_id.delete_ebiz_so_link()
        return message_wizard(f'{len(lines)} payment link(s) removed successfully.', **bulk_regenerate_kwargs,)


class WizardGenerateSelectPaymentLink(models.TransientModel):
    _name = 'wizard.generate.so.select.payment.link'
    _description = "Wizard Generate Select Payment Link"

    record_id = fields.Integer('Record Id')
    order_id = fields.Many2one('sale.order', 'So')
    record_model = fields.Char('Record Model')
    text = fields.Text('Message', readonly=True)

    def generate_selected_record_link(self):
        line_ids = self.env.context.get('selected_line_ids', [])
        lines = self.env['sale.order.payment.link.bulk.line'].browse(line_ids).filtered(lambda r: not r.generated_link)
        return lines._generate_payment_links()
