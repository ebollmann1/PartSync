from odoo import models, api, fields
from odoo.exceptions import UserError, ValidationError
from datetime import datetime
from ..models.ebiz_charge import message_wizard
from odoo.addons.payment_ebizcharge_crm.tools import _prepare_billing_address
from markupsafe import Markup


def _email_transaction_line(line):
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


class EmailInvoice(models.TransientModel):
    _name = 'email.invoice'
    _description = "Email Invoice"

    partner_ids = fields.Many2many('res.partner', string='Customer')
    ebiz_profile_id = fields.Many2one('ebizcharge.instance.config')
    is_surch_enable = fields.Boolean(string=' Surcharge Enabled', related='ebiz_profile_id.is_surcharge_enabled')
    merchant_toggle_sur_per_txn = fields.Boolean(related='ebiz_profile_id.merchant_toggle_sur_per_txn')

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

        tem_check = self.env['email.templates'].search([('template_type_id', '=', 'WebFormEmail'), (
            'instance_id', '=', self.env.context.get('default_ebiz_profile_id'))])
        if tem_check:
            return tem_check[0].id
        else:
            return None

    select_template = fields.Many2one('email.templates', string='Select Template', default=_default_template)
    email_subject = fields.Char(string='Subject', related='select_template.template_subject', readonly=False)
    record_id = fields.Char(string='Record ID')
    model_name = fields.Char(string='Model Name')
    email_customer = fields.Char('')
    amount = fields.Monetary(string='Amount')
    currency_id = fields.Many2one("res.currency", string="Currency", readonly=True, required=True)
    enable_surcharge = fields.Boolean(string='Enable Surcharge', default=True,
                                      help='When enabled, a surcharge fee will be added to all eligible payments processed with a credit card.')

    def _transaction_lines(self, lines):
        item_list = []
        trans_amount = self.amount
        if trans_amount == lines.amount_total:
            order_lines = lines.order_line if lines._name == 'sale.order' else lines.invoice_line_ids
            for line in order_lines:
                item_list.append(_email_transaction_line(line))
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

    def _prepare_email_form(self, sale_order, payment_method, merchant_toggle_sur_per_txn, lines):
        doc_number = str(sale_order.id) if str(sale_order.name) == '/' else str(sale_order.name)
        memo_setting = sale_order.partner_id.ebiz_profile_id.payment_memo_setting
        is_sale = self.env.context.get('active_model') == 'sale.order'
        form = {
            'FormType': 'EmailForm',
            'FromEmail': 'support@ebizcharge.com',
            'FromName': 'EBizCharge',
            'EmailSubject': self.email_subject,
            'EmailAddress': self.email_customer,
            'EmailTemplateID': self.select_template.template_id,
            'EmailTemplateName': self.select_template.name,
            'ShowSavedPaymentMethods': True,
            'CustFullName': sale_order.partner_id.name,
            'TotalAmount': sale_order.amount_total,
            'AmountDue': self.amount,
            'CustomerId': sale_order.partner_id.ebiz_customer_id or sale_order.partner_id.id,
            'SendEmailToCustomer': True,
            'TaxAmount': sale_order.amount_tax if self.amount == sale_order.amount_total else 0,
            'PayByType': payment_method,
            'OrderId': doc_number,
            'SoftwareId': 'Odoo CRM',
            'ProcessingCommand': 'Sale;IsSurchargeEnabled=false' if not self.enable_surcharge and merchant_toggle_sur_per_txn else 'Sale',
            'BillingAddress': _prepare_billing_address(sale_order),
            'LineItems': self._transaction_lines(lines),
        }
        if sale_order.partner_id.ebiz_customer_id:
            form['CustomerId'] = sale_order.partner_id.ebiz_customer_id
        if is_sale:
            form['Date'] = sale_order.date_order.date()
            form['SalesOrderInternalId'] = sale_order.ebiz_internal_id
            form['Description'] = 'SalesOrder'
            form['DocumentTypeId'] = 'SalesOrder'
            form['ShowViewSalesOrderLink'] = True
            form['PoNum'] = sale_order.client_order_ref or sale_order.name
            form['InvoiceNumber'] = " ".join(part for part in [doc_number, sale_order.client_order_ref] if part) \
                if memo_setting == 'dn_pon_pm' else doc_number
        else:
            form['Date'] = sale_order.invoice_date or sale_order.invoice_date_due or ''
            form['InvoiceInternalId'] = sale_order.ebiz_internal_id
            form['Description'] = 'Invoice'
            form['DocumentTypeId'] = 'Invoice'
            form['ShowViewInvoiceLink'] = True
            form['PoNum'] = sale_order.ref or sale_order.name
            form['InvoiceNumber'] = " ".join(part for part in [doc_number, sale_order.ref] if part) \
                if memo_setting == 'dn_pon_pm' else doc_number
        return form

    def invalidate_existing_payment_link(self, record, instance):
        if record.save_payment_link:
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
            ebiz.client.service.DeleteEbizWebFormPayment(**{
                'securityToken': ebiz._generate_security_json(),
                'paymentInternalId': record.payment_internal_id,
            })
            if record and  record.save_payment_link and not record.is_email_request:
                record.message_post(
                    body=Markup(
                        'EBizCharge Payment Link invalidated: <a href="%s" target="_blank">%s</a>' % (
                            record.save_payment_link, record.save_payment_link)
                    ),
                    message_type="comment",
                )
            record.write({'save_payment_link': False})

    def send_email(self):
        try:
            instance = self.partner_ids.ebiz_profile_id or None
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
            sale_order = self.env['account.move'].search([('id', '=', self.record_id)])
            self.invalidate_existing_payment_link(sale_order, instance)
            if self.env.context.get('active_model') == 'sale.order':
                if sale_order.invoice_ids:
                    if sale_order.invoice_ids.amount_residual < self.amount:
                        raise UserError('Amount cannot be greater than amount due!')
                else:
                    if sale_order.amount_total < self.amount:
                        raise UserError('Amount cannot be greater than amount due!')
            else:
                if sale_order.amount_residual < self.amount:
                    raise UserError('Amount cannot be greater than amount due!')

            if '@' not in self.email_customer or '.' not in self.email_customer:
                raise UserError('You might have entered the wrong Email Address!')

            lines = sale_order
            profile = sale_order.partner_id.ebiz_profile_id
            get_merchant_data = profile.merchant_data if profile else False
            get_allow_credit_card_pay = profile.allow_credit_card_pay if profile else False
            payment_method = 'cc'
            if get_merchant_data and get_allow_credit_card_pay:
                payment_method = 'CC,ACH'
            elif get_merchant_data:
                payment_method = 'ACH'
            elif get_allow_credit_card_pay:
                payment_method = 'CC'
            merchant_toggle_sur_per_txn = instance.merchant_toggle_sur_per_txn if instance else False
            ePaymentForm = self._prepare_email_form(sale_order, payment_method, merchant_toggle_sur_per_txn, lines)
            form_url = ebiz.client.service.GetEbizWebFormURL(**{
                'securityToken': ebiz._generate_security_json(),
                'ePaymentForm': ePaymentForm
            })

            if self.env.context.get('active_model') == 'sale.order':
                sale_order.action_confirm()
                sale_order.write({
                    'ebiz_invoice_status': 'pending',
                    'payment_internal_id': form_url.split('=')[1],
                })
            else:
                sale_order.write({
                    'payment_internal_id': form_url.split('=')[1],
                    'ebiz_invoice_status': 'pending',
                    'date_time_sent_for_email': datetime.now(),
                    'email_for_pending': self.email_customer,
                    'email_received_payments': False,
                    'is_email_request': True,
                    'email_requested_amount': self.amount,
                    'save_payment_link': form_url,
                    'no_of_times_sent': 1,
                })
                if sale_order:
                    message_log = 'New Email Pay Request has been sent to: '+str(self.email_customer)
                    sale_order.message_post(body=message_log)

            return message_wizard('Email pay request has been sent successfully!')

        except Exception as e:
            raise ValidationError(e)


class EmailInvoiceMultiple(models.TransientModel):
    _name = 'multiple.email.invoice'
    _description = "Multiple Email Invoice"

    partner_ids = fields.Many2many('res.partner', string='Customer')
    invoice_ids = fields.Many2many('account.move', string='Invoice')
    select_template = fields.Many2one('email.templates', string='Select Template')
    email_subject = fields.Char(string='Subject')
    record_id = fields.Char(string='Record ID')
    model_name = fields.Char(string='Model Name')
    email_customer = fields.Char('', related='partner_ids.email', readonly=True)
    amount = fields.Monetary(string='Amount')
    currency_id = fields.Many2one("res.currency", string="Currency", readonly=True, required=True)



    def _transaction_lines(self, lines):
        item_list = []
        trans_amount = self.amount
        if trans_amount == lines.amount_total:
            order_lines = lines.order_line if lines._name == 'sale.order' else lines.invoice_line_ids
            for line in order_lines:
                item_list.append(_email_transaction_line(line))
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

    def _prepare_email_form(self, sale_order, lines):
        doc_number = str(sale_order.id) if str(sale_order.name) == '/' else str(sale_order.name)
        memo_setting = sale_order.partner_id.ebiz_profile_id.payment_memo_setting
        is_sale = self.env.context.get('active_model') == 'sale.order'
        form = {
            'FormType': 'EmailForm',
            'FromEmail': 'support@ebizcharge.com',
            'FromName': 'EBizCharge',
            'EmailSubject': self.select_template.template_subject,
            'EmailAddress': sale_order.partner_id.email,
            'EmailTemplateID': self.select_template.template_id,
            'EmailTemplateName': self.select_template.name,
            'ShowSavedPaymentMethods': True,
            'CustFullName': sale_order.partner_id.name,
            'TotalAmount': sale_order.amount_total,
            'AmountDue': self.amount,
            'CustomerId': sale_order.partner_id.ebiz_customer_id or sale_order.partner_id.id,
            'OrderId': doc_number,
            'SendEmailToCustomer': True,
            'TaxAmount': sale_order.amount_tax if self.amount == sale_order.amount_total else 0,
            'BillingAddress': _prepare_billing_address(sale_order),
            'LineItems': self._transaction_lines(lines),
        }
        if sale_order.partner_id.ebiz_customer_id:
            form['CustomerId'] = sale_order.partner_id.ebiz_customer_id
        if is_sale:
            form['Date'] = sale_order.date_order.date()
            form['SalesOrderInternalId'] = sale_order.ebiz_internal_id
            form['Description'] = 'SalesOrder'
            form['DocumentTypeId'] = 'SalesOrder'
            form['ShowViewSalesOrderLink'] = True
            form['PoNum'] = sale_order.client_order_ref or sale_order.name
            form['InvoiceNumber'] = " ".join(part for part in [doc_number, sale_order.client_order_ref] if part) \
                if memo_setting == 'dn_pon_pm' else doc_number
        else:
            form['Date'] = sale_order.invoice_date or sale_order.invoice_date_due or ''
            form['InvoiceInternalId'] = sale_order.ebiz_internal_id
            form['Description'] = 'Invoice'
            form['DocumentTypeId'] = 'Invoice'
            form['ShowViewInvoiceLink'] = True
            form['PoNum'] = sale_order.ref or sale_order.name
            form['InvoiceNumber'] = " ".join(part for part in [doc_number, sale_order.ref] if part) \
                if memo_setting == 'dn_pon_pm' else doc_number
        return form

    def send_email(self):
        try:
            instance = self.partner_ids.ebiz_profile_id or None
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
            sale_order = self.env[self.env.context.get('active_model')].browse(self.env.context.get('active_id'))
            if not sale_order.partner_id.email:
                raise UserError(f'"{sale_order.partner_id.name}" does not contain Email Address!')

            lines = sale_order
            ePaymentForm = self._prepare_email_form(sale_order, lines)
            form_url = ebiz.client.service.GetEbizWebFormURL(**{
                'securityToken': ebiz._generate_security_json(),
                'ePaymentForm': ePaymentForm
            })

            if self.env.context.get('active_model') == 'sale.order':
                sale_order.action_confirm()
                sale_order.write({
                    'ebiz_invoice_status': 'pending',
                    'payment_internal_id': form_url.split('=')[1],
                })
            else:
                sale_order.write({
                    'payment_internal_id': form_url.split('=')[1],
                    'is_email_request': True,
                    'ebiz_invoice_status': 'pending',
                })

            return message_wizard('Email has been sent successfully!')

        except Exception as e:
            raise ValidationError(e)


class EmailInvoiceMultiplePayments(models.TransientModel):
    _name = 'multiple.email.invoice.payments'
    _description = "Multiple Email Invoice Payments"

    partner_ids = fields.Many2many('res.partner', string='Customer')
    invoice_ids = fields.Many2many('account.move', string='Invoice')
    select_template = fields.Many2one('email.templates', string='Select Template')
    email_subject = fields.Char(string='Subject')
    record_id = fields.Char(string='Record ID')
    model_name = fields.Char(string='Model Name')
    email_customer = fields.Char('', related='partner_ids.email', readonly=True)
    amount = fields.Monetary(string='Amount')
    currency_id = fields.Many2one("res.currency", string="Currency", readonly=True, required=True)

    def _transaction_lines(self, lines):
        item_list = []
        trans_amount = self.amount
        if trans_amount == lines.amount_total:
            order_lines = lines.order_line if lines._name == 'sale.order' else lines.invoice_line_ids
            for line in order_lines:
                item_list.append(_email_transaction_line(line))
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

    def _prepare_email_form(self, sale_order, lines):
        doc_number = str(sale_order.id) if str(sale_order.name) == '/' else str(sale_order.name)
        memo_setting = sale_order.partner_id.ebiz_profile_id.payment_memo_setting
        is_sale = self.env.context.get('active_model') == 'sale.order'
        form = {
            'FormType': 'EmailForm',
            'FromEmail': 'support@ebizcharge.com',
            'FromName': 'EBizCharge',
            'EmailSubject': self.select_template.template_subject,
            'EmailAddress': sale_order.partner_id.email,
            'EmailTemplateID': self.select_template.template_id,
            'EmailTemplateName': self.select_template.name,
            'ShowSavedPaymentMethods': True,
            'CustFullName': sale_order.partner_id.name,
            'TotalAmount': sale_order.amount_total,
            'AmountDue': self.amount,
            'CustomerId': sale_order.partner_id.ebiz_customer_id or sale_order.partner_id.id,
            'ShowViewInvoiceLink': True,
            'SendEmailToCustomer': True,
            'OrderId': doc_number,
            'TaxAmount': sale_order.amount_tax if self.amount == sale_order.amount_total else 0,
            'BillingAddress': _prepare_billing_address(sale_order),
            'LineItems': self._transaction_lines(lines),
        }
        if sale_order.partner_id.ebiz_customer_id:
            form['CustomerId'] = sale_order.partner_id.ebiz_customer_id
        if is_sale:
            form['Date'] = sale_order.date_order.date()
            form['SalesOrderInternalId'] = sale_order.ebiz_internal_id
            form['Description'] = 'SalesOrder'
            form['DocumentTypeId'] = 'SalesOrder'
            form['ShowViewSalesOrderLink'] = True
            form['PoNum'] = sale_order.client_order_ref or sale_order.name
            form['InvoiceNumber'] = " ".join(part for part in [doc_number, sale_order.client_order_ref] if part) \
                if memo_setting == 'dn_pon_pm' else doc_number
        else:
            form['Date'] = sale_order.invoice_date or sale_order.invoice_date_due or ''
            form['InvoiceInternalId'] = sale_order.ebiz_internal_id
            form['Description'] = 'Invoice'
            form['DocumentTypeId'] = 'Invoice'
            form['ShowViewInvoiceLink'] = True
            form['PoNum'] = sale_order.ref or sale_order.name
            form['InvoiceNumber'] = " ".join(part for part in [doc_number, sale_order.ref] if part) \
                if memo_setting == 'dn_pon_pm' else doc_number
        return form

    def send_email(self):
        try:
            sale_order = self.env[self.env.context.get('active_model')].browse(self.env.context.get('active_id'))
            instance = sale_order.partner_id.ebiz_profile_id or None
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
            if not sale_order.partner_id.email:
                raise UserError(f'"{sale_order.partner_id.name}" does not contain Email Address!')

            lines = sale_order
            ePaymentForm = self._prepare_email_form(sale_order, lines)
            form_url = ebiz.client.service.GetEbizWebFormURL(**{
                'securityToken': ebiz._generate_security_json(),
                'ePaymentForm': ePaymentForm
            })

            if self.env.context.get('active_model') == 'sale.order':
                sale_order.action_confirm()
                sale_order.write({
                    'ebiz_invoice_status': 'pending',
                    'payment_internal_id': form_url.split('=')[1],
                })
            else:
                sale_order.write({
                    'payment_internal_id': form_url.split('=')[1],
                    'is_email_request': True,
                    'ebiz_invoice_status': 'pending',
                })

            return message_wizard('Email has been sent successfully!')

        except Exception as e:
            raise ValidationError(e)
