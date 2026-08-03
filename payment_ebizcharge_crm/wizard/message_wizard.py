from odoo import fields, models, api, _
from datetime import datetime, timedelta
from ..models.ebiz_charge import message_wizard
from markupsafe import Markup


class MessageWizard(models.TransientModel):
    _name = 'message.wizard'
    _description = "Message Wizard"

    def get_default(self):
        return self.env.context.get("message", False)

    text = fields.Text('Message', readonly=True, default=get_default)
    transaction_id = fields.Many2one('emv.device.transaction', string='Transaction')
    is_eligible = fields.Boolean()
    is_surcharge = fields.Boolean()
    surcharge_subtotal = fields.Float()
    surcharge_percentage = fields.Float()
    surcharge_total = fields.Monetary()

    partner_id = fields.Char(string='Partner')
    transaction_type = fields.Char(string='Transaction Type')
    document_number = fields.Char(string='Document Number')
    reference_number = fields.Char(string='Reference Number')
    auth_code = fields.Char(string='Auth Code')
    payment_method = fields.Char(string='Payment Method')
    date_paid = fields.Datetime(string='Date &amp; Time Paid')
    subtotal = fields.Monetary(string='Subtotal')
    surcharge_percent = fields.Char(string='Surcharge %')
    surcharge_amount = fields.Monetary(string='Surcharge Amount')
    avs_street = fields.Char(string='AVS Street')
    avs_zip_code = fields.Char(string='AVS Zip / Postal Code')
    cvv = fields.Char(string='CVV')

    currency_id = fields.Many2one('res.currency')
    is_ach = fields.Boolean()
    enable_surcharge = fields.Boolean(string='Enable Surcharge')
    
    def action_confirm(self):
        # Refresh a bulk parent (sale.order.payment.link.bulk / inv.payment.link.bulk)
        # before returning, so its bulk lines reflect any source-record changes the
        # preceding wizard made (e.g. surcharge toggle from the generate wizard).
        bulk_model = self.env.context.get('bulk_regenerate_model')
        bulk_id = self.env.context.get('bulk_regenerate_id')
        if bulk_model and bulk_id:
            record = self.env[bulk_model].browse(bulk_id).exists()
            if record and hasattr(record, 'regenerate_line_ids'):
                record.regenerate_line_ids()
        if self.transaction_id:
            self.transaction_id.action_check(trans=self.transaction_id.id)
        else:
            return {'type': 'ir.actions.act_window_close'}


class SuccessPaymentMethods(models.TransientModel):
    _name = 'success.payment.methods'
    _description = "Success Payment Methods"

    def get_default(self):
        return self.env.context.get("message", False)

    text = fields.Text('Message', readonly=True, default=get_default)
    wizard_process_id = fields.Many2one('wizard.order.process.transaction')

    def open_register_wizard(self):
        context = dict(self.env.context)
        if 'move_context' in self.env.context:
            context = dict(self.env.context['move_context'])
        context['active_model'] = 'account.move'
        return {
            'name': 'Register Payment',
            'view_type': 'form',
            'view_mode': 'form',
            'view_id': self.env.ref('account.view_account_payment_register_form').id,
            'res_model': 'account.payment.register',
            'type': 'ir.actions.act_window',
            'target': 'new',
            'res_id': self.env.context['active_id'],
            'context': context
        }


class WizardDeleteToken(models.TransientModel):
    _name = 'wizard.token.delete.confirmation'
    _description = "Wizard Token Delete Confirmation"

    record_id = fields.Integer('Record Id')
    record_model = fields.Char('Record Model')
    text = fields.Text('Message', readonly=True)

    def delete_record(self):
        self.env[self.record_model].browse(self.record_id).token_action_archive()
        return message_wizard('The payment method has been deleted successfully!')


class WizardDeleteEmailPay(models.TransientModel):
    _name = 'wizard.delete.email.pay'
    _description = "Wizard Delete Email Pay"

    record_id = fields.Many2one('payment.request.bulk.email', 'Record Id')
    record_model = fields.Char('Record Model')
    text = fields.Text('Message', readonly=True)

    def _prepare_sync_request_values(self, invoice_id, record):
        return {
            'name': record.name,
            'customer_id': invoice_id.partner_id.id,
            'email_id': invoice_id.partner_id.email,
            'invoice_id': invoice_id.id,
            'invoice_date': invoice_id.date,
            'sales_person': self.env.user.id,
            'amount': invoice_id.amount_total,
            "currency_id": invoice_id.currency_id.id,
            'amount_due': invoice_id.amount_residual_signed,
            'tax': invoice_id.amount_untaxed_signed,
            'invoice_due_date': invoice_id.invoice_date_due,
            'sync_transaction_id': self.record_id.id,
        }

    def delete_record(self):
        res_ids = self.env.context.get('selected_line_ids')
        pending_received_msg = self.env.context.get('pending_received')
        records = self.env[self.record_model].browse(res_ids)
        success = 0
        for record in records:
            invoice_id = record.invoice_id
            instance = invoice_id.partner_id.ebiz_profile_id or None

            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
            if pending_received_msg == 'Pending Requests':
                form_url = ebiz.client.service.DeleteEbizWebFormPayment(**{
                    'securityToken': ebiz._generate_security_json(),
                    'paymentInternalId': invoice_id.payment_internal_id,
                })
                if form_url.Status == 'Success':
                    invoice_id.write({'ebiz_invoice_status': 'delete'})
                    success += 1
                    dict2 = self._prepare_sync_request_values(invoice_id, record)
                    new_sync_invoice = self.env['sync.request.payments.bulk'].create(dict2)
                    self.record_id.transaction_history_line_pending = [fields.Command.unlink(record.id)]
                    self.record_id.transaction_history_line = [fields.Command.link(new_sync_invoice.id)]

            elif pending_received_msg == 'Received Email Payments':
                form_url = ebiz.client.service.MarkEbizWebFormPaymentAsApplied(**{
                    'securityToken': ebiz._generate_security_json(),
                    'paymentInternalId': invoice_id.payment_internal_id,
                })

                if form_url.Status == 'Success':
                    invoice_id.write({'email_received_payments': False, 'ebiz_invoice_status': False})
                    success += 1
                    dict2 = self._prepare_sync_request_values(invoice_id, record)
                    new_sync_invoice = self.env['sync.request.payments.bulk'].create(dict2)
                    self.record_id.transaction_history_line_received = [fields.Command.unlink(record.id)]
                    self.record_id.transaction_history_line = [fields.Command.link(new_sync_invoice.id)]

            invoice_id.write({'save_payment_link': False, 'request_amount': 0, 'last_request_amount': 0})
        self.record_id.regenerate_line_ids()
        return message_wizard(f'{success} payment(s)  were successfully removed from {pending_received_msg}!')


class WizardDeletePaymentMethods(models.TransientModel):
    _name = 'wizard.delete.payment.methods'
    _description = "Wizard Delete Payment Methods"

    record_id = fields.Integer('Record Id')
    record_model = fields.Char('Record Model')
    text = fields.Text('Message', readonly=True)

    def delete_record(self):
        res_ids = self.env.context.get('selected_line_ids')
        pending_received_msg = self.env.context.get('pending_received')
        records = self.env[self.record_model].browse(res_ids)
        success = 0
        for record in records:
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=record.customer_id.ebiz_profile_id)
            if pending_received_msg == 'Pending Requests':
                ebiz.client.service.DeleteEbizWebFormPayment(**{
                    'securityToken': ebiz._generate_security_json(),
                    'paymentInternalId': record.payment_internal_id,
                })
                success += 1
                record.sync_transaction_id_pending.transaction_history_line_pending = [fields.Command.delete(record.id)]
            elif pending_received_msg == 'Added Payment Methods':
                ebiz.client.service.MarkEbizWebFormPaymentAsApplied(**{
                    'securityToken': ebiz._generate_security_json(),
                    'paymentInternalId': record.payment_internal_id,
                })
                success += 1
                record.sync_transaction_id_received.transaction_history_line_received = [fields.Command.delete(record.id)]
        if pending_received_msg == 'Pending Requests':
            return message_wizard(f'{success} request(s) were successfully removed from Pending Requests!')
        elif pending_received_msg == 'Added Payment Methods':
            return message_wizard(
                f'{success} payment method(s) were successfully removed from Added Payment Methods!')


class WizardDeleteDownloadLogs(models.TransientModel):
    _name = 'wizard.delete.logs.download'
    _description = "Wizard Delete Logs Download"

    record_id = fields.Integer('Record Id')
    record_model = fields.Char('Record Model')
    text = fields.Text('Message', readonly=True)

    def delete_record(self):
        record_ids = self.env.context.get('record_ids')
        log_ids = self.env['sync.logs'].browse(record_ids)
        success = len(log_ids)
        log_ids.unlink()
        return message_wizard(f'{success} payment(s) were successfully cleared from the Log!')


class WizardDeleteUploadLogs(models.TransientModel):
    _name = 'wizard.delete.upload.logs'
    _description = "Wizard Delete Upload Logs"

    record_id = fields.Integer('Record Id')
    record_model = fields.Char('Record Model')
    text = fields.Text('Message', readonly=True)

    def delete_record(self):
        values = self.env.context.get('list_of_records')
        model_type = self.env.context.get('model')
        success = 0
        for record in values:
            record_to_dell = self.env[model_type].search([('id', '=', record)])
            if record_to_dell:
                record_to_dell.unlink()
                success += 1
        return message_wizard(f'{success} {self.record_model}(s) were successfully cleared from the Log!')


class WizardDeleteInactiveCustomer(models.TransientModel):
    _name = 'wizard.inactive.customers'
    _description = "Wizard Inactive Customers"

    record_id = fields.Integer('Record Id')
    record_model = fields.Char('Record Model')
    text = fields.Text('Message', readonly=True)

    def delete_record(self):
        res_ids = self.env.context.get('selected_line_ids')
        records = self.env['list.of.customers'].browse(res_ids)
        success = 0
        for record in records:
            ebiz_customer = record.customer_id
            if ebiz_customer and ebiz_customer.ebiz_internal_id:
                ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=ebiz_customer.ebiz_profile_id or None)
                ebiz.client.service.MarkCustomerAsInactive(**{
                    'securityToken': ebiz._generate_security_json(),
                    'customerInternalId': ebiz_customer.ebiz_internal_id,
                })
                ebiz_customer.active = False
                success += 1
        return message_wizard(f'{success} customer(s) were successfully deactivated in Odoo and EBizCharge Hub!')


class WizardReceivedEmailPay(models.TransientModel):
    _name = 'wizard.receive.email.pay'
    _description = "Wizard Receive Email Pay"

    record_id = fields.Integer('Record Id')
    odoo_invoice = fields.Many2one('account.move', 'Odoo Invoice')
    text = fields.Text('Message', readonly=True)

    def apply_record(self):
        import ast
        self.odoo_invoice.received_apply_email_after_confirmation(
            ast.literal_eval(f"{self.env.context.get('invoice')}"))


class WizardReceivedEmailPayPaymentLink(models.TransientModel):
    _name = 'wizard.receive.email.payment.link'
    _description = "Wizard Receive Email Payment Link"

    odoo_invoice = fields.Many2one('account.move', 'Odoo Invoice')
    text = fields.Text('Message', readonly=True)
    order_id = fields.Many2one('sale.order', 'Order')
    is_pay_link = fields.Boolean(string='Pay Link')
    invoice_ids = fields.Many2many('account.move', string='Invoices')
    sale_ids = fields.Many2many('sale.order', string='Orders')
    batch_ids = fields.Many2many('sync.batch.processing', string='Batch Processing')

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

            record.save_payment_link = False

    def _handle_payment_link_context(self, record):
        self.invalidate_existing_payment_link(record, record.partner_id.ebiz_profile_id or None)
        profile = record.partner_id.ebiz_profile_id
        instance = profile or False
        is_profile = bool(profile)
        allow_credit_card_pay = profile.enable_cvv if profile else False
        merchant_data = profile.merchant_data if profile else False
        return {
            'name': 'Register Payment',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'custom.register.payment',
            'view_id': False,
            'type': 'ir.actions.act_window',
            'target': 'new',
            'context': {
                'default_amount': record.ebiz_amount_residual,
                'default_date': datetime.now().date(),
                'default_ebiz_receipt_emails': record.partner_id.email,
                'default_order_id': record.id,
                'default_memo': record.name,
                'partner_id': record.partner_id.id,
                'sub_partner_id': record.partner_id.id,
                'default_card_functionality_hide': allow_credit_card_pay,
                'default_ach_functionality_hide': merchant_data,
                'default_is_ebiz_profile': is_profile,
                'default_ebiz_profile_id': instance.id,
                'default_required_security_code': instance.verify_card_before_saving,
            }
        }

    def _handle_batch_processing(self):
        for batch_record in self.batch_ids.filtered('generated_link'):
            invoice = batch_record.invoice_id
            self.invalidate_existing_payment_link(invoice, invoice.partner_id.ebiz_profile_id or None)
        return self.batch_ids.with_context(for_batch_processing=True).process_invoices()

    def _handle_invoice_pay_link(self):
        payment_lines = []
        for inv in self.invoice_ids:
            if inv and inv.payment_state not in ("paid", "in_payment"):
                payment_line = {
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
                }
                payment_lines.append(fields.Command.create(payment_line))
            profile = inv.partner_id.ebiz_profile_id.id
        wiz = self.env['wizard.ebiz.generate.link.payment.bulk'].with_context(
            profile=profile).create(
            {'payment_lines': payment_lines,
             'invoice_link': True,
             'ebiz_profile_id': profile})
        action = self.env.ref('payment_ebizcharge_crm.wizard_generate_link_form_views_action').read()[0]
        action['res_id'] = wiz.id
        action['context'] = self.env.context
        return action

    def _handle_sale_ids(self):
        payment_lines = []
        profile = False
        for order in self.sale_ids:
            payment_lines.append(fields.Command.create({
                "order_id": order.id,
                "partner_id": order.partner_id.id,
                "transaction_type": order.partner_id.ebiz_profile_id.gpl_pay_sale,
                "amount_total_signed": order.amount_total,
                "request_amount": order.ebiz_order_amount_residual,
                "so_payment_link": order.odoo_payment_link,
                "currency_id": self.env.user.currency_id.id,
                "email_id": order.partner_id.email,
                "ebiz_profile_id": order.partner_id.ebiz_profile_id.id,
            }))
            profile = order.partner_id.ebiz_profile_id.id
        wiz = self.env['wizard.generate.so.link.payment'].with_context(
            profile=profile).create(
            {'payment_lines': payment_lines,
             'sale_link': True,
             'ebiz_profile_id': profile})
        action = self.env.ref('payment_ebizcharge_crm.wizard_generate_so_link_form_views_action').read()[0]
        action['res_id'] = wiz.id
        action['context'] = self.env.context
        return action

    def _handle_generate_payment_link(self, record, instance):
        self.invalidate_existing_payment_link(record, instance)
        self.odoo_invoice.request_amount -= self.odoo_invoice.last_request_amount
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generate Payment Link'),
            'res_model': 'ebiz.payment.link.wizard',
            'target': 'new',
            'view_mode': 'form',
            'view_type': 'form',
            'context': {
                'default_ebiz_profile_id': record.partner_id.ebiz_profile_id.id,
                'active_id': record.id,
                'active_model': 'account.move',
            }
        }

    def _handle_email_pay_request(self, record):
        if 'email_pay' in self.env.context and self.odoo_invoice:
            self.odoo_invoice.request_amount -= self.odoo_invoice.last_request_amount
        return {
            'type': 'ir.actions.act_window',
            'name': _('Email Pay Request'),
            'res_model': 'email.invoice',
            'target': 'new',
            'view_mode': 'form',
            'view_type': 'form',
            'context': {
                'default_contacts_to': [fields.Command.set([record.partner_id.id])],
                'default_record_id': record.id,
                'default_partner_ids': [fields.Command.set(record.partner_id.ids)],
                'default_ebiz_profile_id': record.partner_id.ebiz_profile_id.id,
                'default_currency_id': record.currency_id.id,
                'default_amount': record.amount_residual if record.amount_residual else record.amount_total,
                'default_model_name': 'account.move',
                'default_email_customer': str(record.partner_id.email if record.partner_id.email else ''),
                'selection_check': 1,
            }
        }

    def send_email(self):
        record = self.order_id or self.odoo_invoice
        instance = record.partner_id.ebiz_profile_id or None
        if 'from_payment_link' in self.env.context:
            return self._handle_payment_link_context(record)
        elif self.batch_ids:
            return self._handle_batch_processing()
        elif self.is_pay_link and self.invoice_ids:
            return self._handle_invoice_pay_link()
        elif self.sale_ids:
            return self._handle_sale_ids()
        elif self.odoo_invoice and 'email_pay' not in self.env.context:
            return self._handle_generate_payment_link(record, instance)
        else:
            return self._handle_email_pay_request(record)



class WizardCreditNoteValidation(models.TransientModel):
    _name = 'wizard.credit.note.validate'
    _description = "Wizard Credit Note Validate"

    invoice_id = fields.Many2one('account.move')
    text = fields.Text('Message', readonly=True)

    def proceed(self):
        context = dict(self.env.context)
        context['bypass_credit_note_restriction'] = True
        return self.invoice_id.with_context(context).action_reverse()


class EmailPayMessage(models.TransientModel):
    _name = 'wizard.email.pay.message'
    _description = "Wizard Email Pay Message"

    name = fields.Char("Customer")
    success_count = fields.Integer("Success Count")
    failed_count = fields.Integer("Failed Count")
    total = fields.Integer("Total")
    lines_ids = fields.One2many('wizard.email.pay.message.line', 'message_id')


class EmailPayMessageLine(models.TransientModel):
    _name = "wizard.email.pay.message.line"
    _description = "Wizard Email Pay Message Line"

    message_id = fields.Many2one('wizard.email.pay.message')
    status = fields.Char("Status")
    display_tooltip_message = fields.Char("Tooltip Message")
    should_show_icon = fields.Boolean()
    customer_id = fields.Integer("Customer ID")
    email = fields.Char("Email")
    invoice_id = fields.Many2one('account.move', "Number")
    customer_name = fields.Many2one('res.partner', string="Customer")


class MultiPaymentMsg(models.TransientModel):
    _name = 'wizard.multi.payment.message'
    _description = "Wizard Multi Payment Message"

    name = fields.Char("Customer")
    success_count = fields.Integer("Success Count")
    failed_count = fields.Integer("Failed Count")
    total = fields.Integer("Total")
    lines_ids = fields.One2many('wizard.multi.payment.message.line', 'message_id')


class MultiPaymentMsgLine(models.TransientModel):
    _name = "wizard.multi.payment.message.line"
    _description = "Wizard Multi Payment Message Line"

    message_id = fields.Many2one('wizard.multi.payment.message')
    status = fields.Char("Status")
    customer_id = fields.Integer("Customer ID")
    email_address = fields.Char("Email")
    should_show_icon = fields.Boolean()
    display_tooltip_message = fields.Char("Tooltip Message")
    customer_name = fields.Many2one('res.partner', string="Customer")


class MultiTransactionsMsg(models.TransientModel):
    _name = 'wizard.transaction.history.message'
    _description = "Wizard Transaction History Message"

    name = fields.Char("Customer")
    success_count = fields.Integer("Success Count")
    failed_count = fields.Integer("Failed Count")
    lines_ids = fields.One2many('wizard.transaction.history.message.line', 'message_id')


class MultiTransactionsLine(models.TransientModel):
    _name = "wizard.transaction.history.message.line"
    _description = "Wizard Transaction History Message Line"

    message_id = fields.Many2one('wizard.transaction.history.message')
    status = fields.Char("Status")
    customer_id = fields.Char("Customer Id")
    ref_num = fields.Char("Reference Number")
    customer_name = fields.Char("Customer")
    type = fields.Char("Type")
