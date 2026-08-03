from odoo import fields, models, _, api
from datetime import datetime
import logging
from odoo.addons.payment_ebizcharge_crm.tools import _prepare_billing_address
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class EmailPaymentWizard(models.TransientModel):
    _name = 'ebiz.request.payment.bulk'
    _description = "EBiz Request Payment Bulk"

    payment_lines = fields.One2many('ebiz.payment.lines.bulk', 'wizard_id')

    def _default_template(self):
        if 'profile' in self.env.context:
            instances = self.env['ebizcharge.instance.config'].search(
                [('id', '=', self.env.context['profile'])])
            self.env['email.templates'].search(
                [('instance_id', '=', self.env.context['profile'])]).unlink()
        else:
            instances = self.env['ebizcharge.instance.config'].search(
                [('is_valid_credential', '=', True), ('is_active', '=', True)])
            self.env['email.templates'].search([]).unlink()

        for instance in instances:
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
            templates = ebiz.client.service.GetEmailTemplates(**{
                'securityToken': ebiz._generate_security_json()
            })
            if templates:
                for template in templates:
                    odoo_temp = self.env['email.templates'].search(
                        [('template_id', '=', template['TemplateInternalId']), ('instance_id', '=', instance.id)])
                    if not odoo_temp:
                        if template['TemplateTypeId'] != 'TransactionReceiptMerchant' and template[
                            'TemplateTypeId'] != 'TransactionReceiptCustomer':
                            self.env['email.templates'].create({
                                'name': template['TemplateName'],
                                'template_id': template['TemplateInternalId'],
                                'template_subject': template['TemplateSubject'],
                                'template_description': template['TemplateDescription'],
                                'template_type_id': template['TemplateTypeId'],
                                'instance_id': instance.id,
                            })
        profile = self.env.context['profile']
        tem_check = self.env['email.templates'].search([('template_type_id', '=', 'WebFormEmail'), ('instance_id', '=', profile)])
        return tem_check[0].id if tem_check else None

    select_template = fields.Many2one('email.templates', string='Select Template', default=_default_template)
    email_subject = fields.Char(string='Subject', related='select_template.template_subject', readonly=False)
    ebiz_profile_id = fields.Many2one('ebizcharge.instance.config', string='EBizCharge Merchant Account')

    def _prepare_email_form(self, invoice_id, record, payment_method, merchant_toggle_sur_per_txn, lines):
        invoice_number = str(invoice_id.id) if str(invoice_id.name) == '/' else str(invoice_id.name)
        memo_setting = invoice_id.partner_id.ebiz_profile_id.payment_memo_setting
        form = {
            'FormType': 'EmailForm',
            'FromEmail': 'support@ebizcharge.com',
            'FromName': 'EBizCharge',
            'EmailSubject': self.email_subject,
            'EmailAddress': record.email_id,
            'EmailTemplateID': self.select_template.template_id,
            'EmailTemplateName': self.select_template.name,
            'ShowSavedPaymentMethods': True,
            'CustFullName': invoice_id.partner_id.name,
            'TotalAmount': invoice_id.amount_total,
            'AmountDue': record.amount_due,
            'DocumentTypeId': 'Invoice',
            'ShippingAmount': record.amount_due,
            'PayByType': payment_method,
            'CustomerId': invoice_id.partner_id.ebiz_customer_id or invoice_id.partner_id.id,
            'ShowViewInvoiceLink': True,
            'SendEmailToCustomer': True,
            'TaxAmount': invoice_id.amount_tax if invoice_id.amount_total == record.amount_due else 0,
            'SoftwareId': 'Odoo CRM',
            'ProcessingCommand': 'Sale;IsSurchargeEnabled=false' if not record.enable_surcharge and merchant_toggle_sur_per_txn else 'Sale',
            'Date': invoice_id.invoice_date or invoice_id.invoice_date_due or '',
            'OrderId': invoice_number,
            'BillingAddress': _prepare_billing_address(invoice_id),
            'LineItems': self._transaction_lines(lines, amt_due=record.amount_due),
            'InvoiceInternalId': invoice_id.ebiz_internal_id,
            'Description': 'Invoice',
            'PoNum': invoice_id.ref or invoice_id.name,
            'InvoiceNumber': " ".join(part for part in [invoice_number, invoice_id.ref] if part)
                if memo_setting == 'dn_pon_pm' else invoice_number,
        }
        if invoice_id.partner_id.ebiz_customer_id:
            form['CustomerId'] = invoice_id.partner_id.ebiz_customer_id
        return form

    def send_email(self):
        try:
            resp_lines = []
            success = 0
            failed = 0
            total_count = len(self.payment_lines)
            if not self.payment_lines:
                raise UserError('Please select a record first!')

            for record in self.payment_lines:
                invoice_id = record.invoice_id
                instance = record.customer_name.ebiz_profile_id or None

                ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
                resp_line = {'customer_name': record.customer_name.id, 'customer_id': record.customer_name.id,
                             'invoice_id': invoice_id.id, 'email': record.email_id}

                if record.email_id and '@' in record.email_id and '.' in record.email_id:
                    if invoice_id.state != 'posted':
                        invoice_id.action_post()

                    if not invoice_id.ebiz_internal_id:
                        invoice_id.sync_to_ebiz()

                    if invoice_id.amount_residual < record.amount_due:
                        raise UserError('Amount cannot be greater than amount due!')


                    lines = invoice_id
                    profile = invoice_id.partner_id.ebiz_profile_id
                    get_merchant_data = profile.merchant_data if profile else False
                    get_allow_credit_card_pay = profile.allow_credit_card_pay if profile else False
                    payment_method = 'cc'
                    if get_merchant_data and get_allow_credit_card_pay:
                        payment_method = 'CC,ACH'
                    elif get_merchant_data:
                        payment_method = 'ACH'
                    elif get_allow_credit_card_pay:
                        payment_method = 'CC'

                    merchant_toggle_sur_per_txn = profile.merchant_toggle_sur_per_txn if profile else False
                    ePaymentForm = self._prepare_email_form(invoice_id, record, payment_method, merchant_toggle_sur_per_txn, lines)

                    form_url = ebiz.client.service.GetEbizWebFormURL(**{
                        'securityToken': ebiz._generate_security_json(),
                        'ePaymentForm': ePaymentForm
                    })

                    invoice_id.write(self._prepare_invoice_update_params(form_url, record))

                    resp_line['status'] = 'Success'
                    resp_line['should_show_icon'] = False
                    success += 1
                    email_invoices_obj = record.sync_request_id.sync_transaction_id
                    date_check = False
                    if invoice_id.date_time_sent_for_email:
                        date_check = 'due in 3 days' if (datetime.now() - invoice_id.date_time_sent_for_email).days <= 3 \
                            else '3 days overdue'
                    dict2 = self._prepare_sync_request_values(invoice_id, record, date_check)
                    sync_invoice_pending_id = self.env['sync.request.payments.bulk.pending'].create(dict2)
                    email_invoices_obj.write({
                        'transaction_history_line_pending': [fields.Command.link(sync_invoice_pending_id.id)],
                        'transaction_history_line': [fields.Command.unlink(record.sync_request_id.id)],
                    })

                elif not record.email_id:
                    resp_line['status'] = 'Failed (No Email Address)'
                    resp_line['display_tooltip_message'] = 'No Email Address'
                    resp_line['should_show_icon'] = True
                    failed += 1
                else:
                    resp_line['status'] = 'Failed (Invalid Email Address)'
                    resp_line['display_tooltip_message'] = 'Invalid Email Address'
                    resp_line['should_show_icon'] = True
                    failed += 1

                resp_lines.append(fields.Command.create(resp_line))

            else:
                wizard = self.env['wizard.email.pay.message'].create({'name': 'email_pay', 'lines_ids': resp_lines,
                                                                      'success_count': success,
                                                                      'failed_count': failed,
                                                                      'total': total_count})
                return {'type': 'ir.actions.act_window',
                        'name': _('Email Pay for Invoices'),
                        'res_model': 'wizard.email.pay.message',
                        'target': 'new',
                        'res_id': wizard.id,
                        'view_mode': 'form',
                        'views': [[False, 'form']],
                        'context':
                            self.env.context,
                        }

        except Exception as e:
            raise ValidationError(e)

    def _prepare_sync_request_values(self, invoice_id, record, date_check):
        return {
            'name': record['name'],
            'customer_id': invoice_id.partner_id.id,
            'invoice_id': invoice_id.id,
            'invoice_date': invoice_id.date,
            'email_id': record.email_id if record.email_id else invoice_id.partner_id.email,
            'sales_person': self.env.user.id,
            'amount': invoice_id.amount_total,
            "currency_id": record.currency_id.id,
            'amount_due': invoice_id.amount_residual_signed,
            'tax': invoice_id.amount_untaxed_signed,
            'date_and_time_Sent': invoice_id.date_time_sent_for_email or None,
            'over_due_status': date_check if date_check else None,
            'invoice_due_date': invoice_id.invoice_date_due,
            'sync_transaction_id_pending': record.sync_request_id.sync_transaction_id.id,
            'ebiz_status': 'Pending' if invoice_id.ebiz_invoice_status == 'pending' else invoice_id.ebiz_invoice_status,
            'email_requested_amount': invoice_id.email_requested_amount,
            'no_of_times_sent': invoice_id.no_of_times_sent,
        }

    def _prepare_invoice_update_params(self, form_url, record):
        return {
            'payment_internal_id': form_url.split('=')[1],
            'ebiz_invoice_status': 'pending',
            'date_time_sent_for_email': datetime.now(),
            'email_for_pending': record.email_id,
            'email_requested_amount': record.amount_due,
            'email_received_payments': False,
            'save_payment_link': form_url,
            'no_of_times_sent': 1,
        }

    def _transaction_line(self, line):
        if line.price_subtotal != 0:
            qty = line.product_uom_qty if hasattr(line, 'product_uom_qty') else line.quantity
            taxable = False
            tax = 0
            if line._name == 'account.move.line':
                taxable = bool(line.tax_ids)
            elif line._name == 'sale.order.line':
                taxable = bool(line.tax_ids)
                tax = line.price_tax
            return {
                'SKU': line.product_id.id,
                'ProductName': line.product_id.name,
                'Description': line.name,
                'UnitPrice': line.price_unit,
                'Taxable': taxable,
                'TaxAmount': tax if taxable else 0,
                'Qty': str(qty),
                'DiscountRate': line.discount,
            }

    def _transaction_lines(self, lines, amt_due=None):
        item_list = []
        trans_amount = amt_due
        
        if trans_amount == lines.amount_total:
            order_lines = lines.order_line if lines._name == 'sale.order' else lines.invoice_line_ids
            for line in order_lines:
                item_list.append(self._transaction_line(line))
        else:
            description = 'Inv# ' + str(lines.name) if lines._name == "account.move" else 'Order# ' + str(lines.name)
            item_list.append({
                'SKU': lines.name,
                'ProductName': description,
                'Description': description,
                'UnitPrice': trans_amount,
                'Taxable': 0,
                'TaxAmount': 0,
                'Qty': 1,
                'DiscountRate': 0,
            })
        return {'TransactionLineItem': item_list}


class EBizPaymentLines(models.TransientModel):
    _name = 'ebiz.payment.lines.bulk'
    _description = "EBiz Payment Lines Bulk"

    wizard_id = fields.Many2one('ebiz.request.payment.bulk')
    sync_request_id = fields.Many2one('sync.request.payments.bulk')

    name = fields.Char(string='Number')
    customer_name = fields.Many2one('res.partner', string='Customer')
    amount_due = fields.Float(string='Amount Due')
    check_box = fields.Boolean('Select')
    email_id = fields.Char(string='Email ID')
    invoice_id = fields.Many2one('account.move', string='Invoice ID')
    currency_id = fields.Many2one('res.currency', string='Company Currency')
    select_template = fields.Many2one('email.templates', string='Select Template')
    email_subject = fields.Char(string='Subject', related='select_template.template_subject', readonly=False)
    ebiz_profile_id = fields.Many2one('ebizcharge.instance.config')
    enable_surcharge = fields.Boolean(string='Surcharge')

    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        for rec, vals in zip(res, vals_list):
            if 'ebiz_profile_id' in vals:
                tem_check = self.env['email.templates'].search(
                    [('template_type_id', '=', 'WebFormEmail'), ('instance_id', '=', vals['ebiz_profile_id'])])
                if tem_check:
                    rec.write({'select_template': tem_check[0].id})
        return res
