from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
from werkzeug import urls
from markupsafe import Markup
from odoo.addons.payment_ebizcharge_crm.tools import _prepare_billing_address, _transaction_lines


class PaymentLinkWizardInh(models.TransientModel):
    _inherit = 'payment.link.wizard'
    _description = "Generate Payment Link"

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        res_id = self.env.context.get('active_id')
        res_model = self.env.context.get('active_model')
        if res_id and res_model:
            res.update({'res_model': res_model, 'res_id': res_id})
            res.update(
                self.env[res_model].browse(res_id)._get_default_payment_link_values()
            )
            if res_model == 'account.move':
                self.env[res_model].browse(res_id).write({'odoo_payment_link': True})
        return res


    @api.depends('amount', 'currency_id', 'partner_id', 'company_id')
    def _compute_link(self):
        for payment_link in self:
            related_document = self.env[payment_link.res_model].browse(payment_link.res_id)
            base_url = related_document.get_base_url()  # Generate links for the right website.
            url = self._prepare_url(base_url, related_document)
            query_params = self._prepare_query_params(related_document)
            anchor = self._prepare_anchor()
            if '?' in url:
                payment_link.link = f'{url}&{urls.url_encode(query_params)}{anchor}'
            else:
                payment_link.link = f'{url}?{urls.url_encode(query_params)}{anchor}'
            if payment_link.link:
                if payment_link.res_model in ('account.move', 'sale.order'):
                    doc = self.env[payment_link.res_model].browse(payment_link.res_id)
                    if doc:
                        doc.write({'odoo_payment_link_doc': payment_link.link})
                        doc._log_pay_link()


class EBizPaymentLinkWizard(models.TransientModel):
    _name = "ebiz.payment.link.wizard"
    _description = "Generate Payment Link"

    @api.model
    def default_get(self, fields):
        res = super().default_get(fields)
        res_id = self.env.context.get('active_id')
        res_model = self.env.context.get('active_model')
        res.update({'res_id': res_id, 'res_model': res_model})
        amount_field = 'amount_residual' if res_model == 'account.move' else 'amount_total'
        if res_id and res_model == 'account.move':
            record = self.env[res_model].browse(res_id)
            res.update({
                'description': record.payment_reference,
                'amount': record[amount_field],
                'currency_id': record.currency_id.id,
                'partner_id': record.partner_id.id,
                'amount_max': record[amount_field],
            })
        if res_id and res_model == 'sale.order':
            record = self.env[res_model].browse(res_id)
            res.update({
                'description': record.name,
                'amount': record[amount_field],
                'currency_id': record.currency_id.id,
                'partner_id': record.partner_id.id,
                'amount_max': record[amount_field],
            })
        return res

    res_model = fields.Char('Related Document Model', required=True)
    res_id = fields.Integer('Related Document ID', required=True)
    amount = fields.Monetary(currency_field='currency_id', required=True)
    amount_max = fields.Monetary(currency_field='currency_id')
    currency_id = fields.Many2one('res.currency')
    partner_id = fields.Many2one('res.partner')
    partner_email = fields.Char(related='partner_id.email')
    link = fields.Char(string='Payment Link')
    description = fields.Char('Payment Ref')
    link_check_box = fields.Boolean('Link Check Box', default=False)
    ebiz_profile_id = fields.Many2one('ebizcharge.instance.config')

    def _default_template(self):
        if 'default_ebiz_profile_id' in self.env.context:
            instances = self.env['ebizcharge.instance.config'].search(
                [('id', '=', self.env.context['default_ebiz_profile_id'])])
            self.env['email.templates'].search(
                [('instance_id', '=', self.env.context['default_ebiz_profile_id'])]).unlink()
        else:
            instances = self.env['ebizcharge.instance.config'].search(
                [('is_valid_credential', '=', True), ('is_active', '=', True)])
            self.env['email.templates'].search([]).unlink()
        for instance in instances:
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
            templates = ebiz.client.service.GetEmailTemplates(**{
                'securityToken': ebiz._generate_security_json(),
            })
            if templates:
                for template in templates:
                    odoo_temp = self.env['email.templates'].search(
                        [('template_id', '=', template['TemplateInternalId']), ('instance_id', '=', instance.id)])
                    if not odoo_temp:
                        if template['TemplateTypeId'] not in ('TransactionReceiptMerchant', 'TransactionReceiptCustomer'):
                            self.env['email.templates'].create({
                                'name': template['TemplateName'],
                                'template_id': template['TemplateInternalId'],
                                'template_subject': template['TemplateSubject'],
                                'template_description': template['TemplateDescription'],
                                'template_type_id': template['TemplateTypeId'],
                                'instance_id': instance.id,
                            })

        tem_check = self.env['email.templates'].search([('template_type_id', '=', 'WebFormEmail'),
            ('instance_id', '=', self.env.context.get('default_ebiz_profile_id'))])

        if tem_check:
            return tem_check[0].id
        else:
            return None

    select_template = fields.Many2one('email.templates', string='Select Template', default=_default_template)
    is_sale_order = fields.Boolean(string='Sale')
    transaction_type = fields.Selection([('pre_auth', 'Pre-Authorize'),
                                         ('deposit', 'Deposit')], string='Transaction Type', default='pre_auth',
                                        index=True)
    enable_surcharge = fields.Boolean(string='Enable Surcharge')

    @api.onchange('amount', 'description')
    def _onchange_amount(self):
        if self.amount <= 0:
            raise ValidationError(_("The value of the payment amount must be positive."))

    def _prepare_paylink_form(self, record, res_model, payment_method, lines):
        template = self.select_template
        doc_number = str(record.id) if str(record.name) == '/' else str(record.name)
        memo_setting = record.partner_id.ebiz_profile_id.payment_memo_setting
        merchant_account_id = record.partner_id.ebiz_profile_id
        merchant_toggle_sur_per_txn = merchant_account_id.merchant_toggle_sur_per_txn if merchant_account_id else False
        form = {
            'FormType': 'PayLinkOnly',
            'FromEmail': 'support@ebizcharge.com',
            'FromName': 'EBizCharge',
            'EmailSubject': template.template_subject,
            'EmailAddress': record.partner_id.email or ' ',
            'EmailTemplateID': template.template_id,
            'EmailTemplateName': template.name,
            'ShowSavedPaymentMethods': True,
            'CustFullName': record.partner_id.name,
            'TotalAmount': record.amount_total,
            'PayByType': payment_method,
            'AmountDue': self.amount,
            'ShippingAmount': 0,
            'CustomerId': record.partner_id.ebiz_customer_id or record.partner_id.id,
            'SendEmailToCustomer': False,
            'TaxAmount': record.amount_tax if self.amount == record.amount_total else 0,
            'SoftwareId': 'ODOOPayLinkOnly',
            'OrderId': doc_number,
            'BillingAddress': _prepare_billing_address(record),
            'LineItems': _transaction_lines(lines),
        }
        if record.partner_id.ebiz_customer_id:
            form['CustomerId'] = record.partner_id.ebiz_customer_id
        if res_model == 'account.move':
            form['ProcessingCommand'] = 'Sale;IsSurchargeEnabled=false' if not self.enable_surcharge and merchant_toggle_sur_per_txn else 'Sale'
            form['ShowViewInvoiceLink'] = True
            form['InvoiceInternalId'] = record.ebiz_internal_id
            form['Description'] = 'Invoice'
            form['DocumentTypeId'] = 'Invoice'
            form['PoNum'] = record.ref or record.name
            form['InvoiceNumber'] = " ".join(part for part in [doc_number, record.ref] if part) \
                if memo_setting == 'dn_pon_pm' else doc_number
            form['Date'] = record.invoice_date or record.invoice_date_due or ''
        elif res_model == 'sale.order':
            surcharge_suffix = ';IsSurchargeEnabled=false' if not self.enable_surcharge and merchant_toggle_sur_per_txn else ''
            if self.transaction_type == 'pre_auth':
                form['ProcessingCommand'] = 'AuthOnly' + surcharge_suffix
                form['PayByType'] = 'CC'
            else:
                form['ProcessingCommand'] = 'Sale' + surcharge_suffix
            form['ShowViewSalesOrderLink'] = True
            form['SalesOrderInternalId'] = record.ebiz_internal_id
            form['Description'] = 'SalesOrder'
            form['DocumentTypeId'] = 'SalesOrder'
            form['PoNum'] = record.client_order_ref or record.name
            form['InvoiceNumber'] = " ".join(part for part in [doc_number, record.client_order_ref] if part) \
                if memo_setting == 'dn_pon_pm' else doc_number
            form['Date'] = record.date_order
        return form

    def generate_link(self):
        try:
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=self.ebiz_profile_id)
            res_id = self.env.context.get('active_id')
            res_model = self.env.context.get('active_model')
            record = self.env[res_model].browse(res_id)
            if not self.select_template:
                if 'default_ebiz_profile_id' in self.env.context:
                    instances = self.env['ebizcharge.instance.config'].search(
                        [('id', '=', self.env.context['default_ebiz_profile_id'])])
                    self.env['email.templates'].search(
                        [('instance_id', '=', self.env.context['default_ebiz_profile_id'])]).unlink()
                else:
                    instances = self.env['ebizcharge.instance.config'].search(
                        [('is_valid_credential', '=', True), ('is_active', '=', True)])
                    self.env['email.templates'].search([]).unlink()
                for instance in instances:
                    ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
                    templates = ebiz.client.service.GetEmailTemplates(**{
                        'securityToken': ebiz._generate_security_json(),
                    })
                    if templates:
                        for template in templates:
                            odoo_temp = self.env['email.templates'].search(
                                [('template_id', '=', template['TemplateInternalId']), ('instance_id', '=', instance.id)])
                            if not odoo_temp:
                                if template['TemplateTypeId'] not in ('TransactionReceiptMerchant', 'TransactionReceiptCustomer'):
                                    self.env['email.templates'].create({
                                        'name': template['TemplateName'],
                                        'template_id': template['TemplateInternalId'],
                                        'template_subject': template['TemplateSubject'],
                                        'template_description': template['TemplateDescription'],
                                        'template_type_id': template['TemplateTypeId'],
                                        'instance_id': instance.id,
                                    })
                template_type_id = 'WebFormEmail' if not self.is_sale_order else 'SalesOrderWebFormEmail'
                tem_check = self.env['email.templates'].search([('template_type_id', '=', template_type_id), (
                    'instance_id', '=', self.env.context.get('default_ebiz_profile_id'))])

                if tem_check:
                    self.select_template = tem_check[0].id

            if not self.select_template:
                raise UserError('Configuration required. Please set a default email template inside the Admin Portal to generate payment link.')
            if self.is_sale_order and self.transaction_type == 'pre_auth' and self.amount < record.ebiz_amount_residual:
                raise UserError('Amount cannot be less than the original document amount for Pre-Auth.')

            lines = record.order_line if res_model == 'sale.order' else record.invoice_line_ids
            profile = record.partner_id.ebiz_profile_id
            get_merchant_data = profile.merchant_data if profile else False
            get_allow_credit_card_pay = profile.allow_credit_card_pay if profile else False
            payment_method = 'CC'
            if get_merchant_data and get_allow_credit_card_pay:
                payment_method = 'CC,ACH'
            elif get_merchant_data:
                payment_method = 'ACH'
            elif get_allow_credit_card_pay:
                payment_method = 'CC'

            if 'from_bulk' in self.env.context:
                amount = self.env.context['requested_amount']
                record.write({'request_amount': amount, 'last_request_amount': amount})
                self.amount = amount
            else:
                record.write({'request_amount': record.request_amount + self.amount, 'last_request_amount': self.amount})

            if res_model == 'account.move':
                record.write({'ebiz_payment_link': 'pending'})
                if round(self.amount, 2) > round(record.amount_residual, 2):
                    raise UserError("Requested Amount cannot be greater than Invoice Amount.")
            if self.amount < 0 or self.amount == 0:
                raise UserError('Amount cannot be Zero/Negative.')
            ePaymentForm = self._prepare_paylink_form(record, res_model, payment_method, lines)
            if record.save_payment_link:
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
            form_url = ebiz.client.service.GetEbizWebFormURL(**{
                'securityToken': ebiz._generate_security_json(),
                'ePaymentForm': ePaymentForm
            })
            if res_model in ('account.move', 'sale.order'):
                if record.is_email_request:
                    message_log = 'Email Pay Request sent to: ' + str(record.email_for_pending) + '  has been invalidated'
                    record.message_post(body=message_log)
                elif record.save_payment_link:
                    record.message_post(
                        body=Markup(
                            'EBizCharge Payment Link invalidated: <a href="%s" target="_blank">%s</a>' % (
                                form_url, form_url)
                        ),
                        message_type="comment",
                    )

                record.write({'save_payment_link': form_url, 'is_email_request': False, 'ebiz_invoice_status': 'delete'})
                if form_url:
                    record.message_post(
                        body=Markup(
                            'New EBizCharge Payment Link has been generated: <a href="%s" target="_blank">%s</a>' % (
                                form_url, form_url)
                        ),
                        message_type="comment",
                    )

            record.write({'save_payment_link': form_url, 'payment_internal_id': form_url.split('=')[1]})
            if not self.link_check_box:
                return {'type': 'ir.actions.act_window',
                        'name': _('Copy Payment Link'),
                        'res_model': 'ebiz.payment.link.copy',
                        'target': 'new',
                        'view_mode': 'form',
                        'view_type': 'form',
                        'context': {
                            'default_link': form_url,
                        }}
        except Exception as e:
            raise ValidationError(e)



class EBizPaymentLink(models.TransientModel):
    _name = "ebiz.payment.link.copy"
    _description = "Copy Payment Link"

    link = fields.Char(string='Payment Link')
    copy_link_lines = fields.One2many('ebiz.payment.link.copy.line', 'wizard_id', string='Copy Lines')



class EBizPaymentLinkLine(models.TransientModel):
    _name = "ebiz.payment.link.copy.line"
    _description = "Copy Payment Link Lines"

    link = fields.Char(string='Payment Link')
    wizard_id = fields.Many2one('ebiz.payment.link.copy', string='Copy line')
    invoice_id = fields.Many2one('account.move', string='Invoices')
    number = fields.Char(string='Number')


