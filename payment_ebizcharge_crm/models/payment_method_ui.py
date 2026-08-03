# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
from datetime import datetime, timedelta
from .ebiz_charge import message_wizard

_logger = logging.getLogger(__name__)


class PaymentMethodUI(models.Model):
    _name = 'payment.method.ui'
    _description = "Payment Method Ui"

    def get_default_company(self):
        company_ids = self.env.context.get('allowed_company_ids') or []
        instances = self.env['ebizcharge.instance.config'].search([
            ('is_active', '=', True), '|',
            ('company_ids', '=', False),
            ('company_ids', 'in', company_ids),
        ])
        return instances.company_ids.ids

    name = fields.Char(string='Request Payments Via Email', default='Request Payment Methods')
    is_adjustment = fields.Char(string='Is Adjustment')
    transaction_history_line = fields.One2many('list.ebiz.customers', 'sync_transaction_id', copy=True)
    transaction_history_line_pending = fields.One2many('list.pending.payments.methods',
                                                       'sync_transaction_id_pending', copy=True)
    transaction_history_line_received = fields.One2many('list.received.payments.methods',
                                                        'sync_transaction_id_received', copy=True)
    add_filter = fields.Boolean(string='Filters')
    customer_selection = fields.Selection([
        ('all_customers', 'All Customers'),
        ('no_save_card', 'Customers with no saved cards'),
        ('no_save_back_ach', 'Customers with no saved bank accounts'),
        ('no_payment_method', 'Customers with no saved payment methods'),
        ('card_expiring_soon', 'Customers with cards expiring soon'),
        ('expired_card', 'Customers with expired cards'),
    ], string='Display', help="Select which customer you'd like to display", default='all_customers')
    is_reopened = fields.Boolean()
    start_date = fields.Date(string='From Date')
    end_date = fields.Date(string='To Date')
    start_date_received = fields.Date(string='From Date Received')
    end_date_received = fields.Date(string='To Date Received')
    show_hide_div_send = fields.Boolean("Show Send")
    show_hide_div_pending = fields.Boolean("Show Pending")
    show_hide_div_added = fields.Boolean("Show")
    company_ids = fields.Many2many('res.company', compute='compute_company')
    ebiz_profile_id = fields.Many2one('ebizcharge.instance.config', string='EBizCharge Merchant Account')
    ebiz_profile_pending_id = fields.Many2one('ebizcharge.instance.config',
                                              string='EBizCharge Pending Merchant Account')
    ebiz_profile_received_id = fields.Many2one('ebizcharge.instance.config',
                                               string='EBizCharge Received Merchant Account')

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = 'Request Payment Methods'

    @api.depends('ebiz_profile_id')
    def compute_company(self):
        self.company_ids = self.env.context.get('allowed_company_ids')

    def create_send_request_record(self):
        list_of_customers = [fields.Command.clear()]
        profile = int(self.env['ebizcharge.instance.config'].get_upload_instance(active_model='payment.method.ui', active_id=self))
        if profile:
            self.ebiz_profile_id = profile
            self.start_date = self.ebiz_profile_id._default_get_start()
            self.end_date = self.ebiz_profile_id._default_get_end_date()

        if self.ebiz_profile_id:
            customers = self.env['res.partner'].search(
                [('ebiz_internal_id', '!=', False), ('ebiz_profile_id', '=', self.ebiz_profile_id.id)])
        else:
            customers = self.env['res.partner'].search([('ebiz_internal_id', '!=', False)])

        list_of_customers += [
            fields.Command.create({
                'customer_id': customer.id,
                'email_id': customer.email,
                'customer_phone': customer.phone,
                'customer_city': customer.city,
                'sync_transaction_id': self.id,
            })
            for customer in customers
        ]
        return list_of_customers

    def create_pending_request_record(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            return message_wizard('From Date should be lower than the To date!', 'Invalid Date')
        list_of_pending = [fields.Command.clear()]
        profile_obj = self.env['ebizcharge.instance.config']
        default_instance = profile_obj.search(
            [('is_valid_credential', '=', True), ('is_default', '=', True), ('is_active', '=', True), '|',
             ('company_ids', '=', False),
             ('company_ids', 'in', self.env.context.get('allowed_company_ids'))],
            limit=1)
        if not self.ebiz_profile_pending_id:
            if default_instance and (not default_instance.company_ids or
                    default_instance.company_ids.ids in self.env.context.get('allowed_company_ids')):
                profile = default_instance.id
            else:
                profile = profile_obj.search(
                    [('is_valid_credential', '=', True), ('is_active', '=', True), '|',
                     ('company_ids', '=', False), ('company_ids', 'in', self.env.company.ids)], limit=1).id
            self.ebiz_profile_pending_id = profile
            self.start_date = self.ebiz_profile_pending_id._default_get_start()
            self.end_date = self.ebiz_profile_pending_id._default_get_end_date()
        list_of_pending.extend(
            self.fetch_pending_payments(self.start_date, self.end_date, self.ebiz_profile_pending_id))
        if 'from_pending_button' not in self.env.context:
            return list_of_pending
        else:
            self.transaction_history_line_pending = list_of_pending

    def create_received_request_record(self):
        if self.start_date_received and self.end_date_received and self.start_date_received > self.end_date_received:
            return message_wizard('From Date should be lower than the To date!', 'Invalid Date')
        list_of_received = [fields.Command.clear()]
        profile_obj = self.env['ebizcharge.instance.config']
        default_instance = profile_obj.search(
            [('is_valid_credential', '=', True), ('is_default', '=', True), ('is_active', '=', True), '|',
             ('company_ids', '=', False),
             ('company_ids', 'in', self.env.context.get('allowed_company_ids'))],
            limit=1)
        if not self.ebiz_profile_received_id:
            if default_instance and (not default_instance.company_ids or
                    default_instance.company_ids.ids in self.env.context.get('allowed_company_ids')):
                profile = default_instance.id
            else:
                profile = profile_obj.search(
                    [('is_valid_credential', '=', True), ('is_active', '=', True), '|',
                     ('company_ids', '=', False), ('company_ids', 'in', self.env.company.ids)], limit=1).id
            self.ebiz_profile_received_id = profile
            self.start_date_received = self.ebiz_profile_received_id._default_get_start()
            self.end_date_received = self.ebiz_profile_received_id._default_get_end_date()
        list_of_received.extend(
            self.fetch_received_payments(self.start_date_received, self.end_date_received,
                                         self.ebiz_profile_received_id))
        if 'from_received_button' not in self.env.context:
            return list_of_received
        else:
            self.transaction_history_line_received = list_of_received

    def action_open_request_payment_methods(self):
        rec = self.create({})
        rec.create_default_records()
        return {
            'name': _('Request Payment Methods'),
            'type': 'ir.actions.act_window',
            'res_model': 'payment.method.ui',
            'res_id': rec.id,
            'view_id': self.env.ref('payment_ebizcharge_crm.form_view_request_payment_method_ui', False).id,
            'view_mode': 'form',
            'target': 'inline',
        }

    def create_default_records(self):
        self.write({
            'transaction_history_line': self.create_send_request_record(),
            'transaction_history_line_pending': self.create_pending_request_record(),
            'transaction_history_line_received': self.create_received_request_record(),
        })

    def search_customers(self):
        try:
            if not self.customer_selection:
                raise UserError('No option selected!')
            return getattr(self, f'_search_{self.customer_selection}')()
        except Exception as e:
            raise UserError(e)

    def _apply_customer_lines(self, customers):
        self.transaction_history_line = [fields.Command.clear()] + [
            fields.Command.create({
                'customer_id': c.id,
                'email_id': c.email,
                'customer_phone': c.phone,
                'customer_city': c.city,
                'sync_transaction_id': self.id,
            }) for c in customers
        ]

    def _get_instances(self):
        return self.ebiz_profile_id or self.env['ebizcharge.instance.config'].search(
            [('is_valid_credential', '=', True)])

    def _find_local_customer(self, customer_id=None, internal_id=None):
        domain = [('ebiz_internal_id', '!=', False)]
        if self.ebiz_profile_id:
            domain.append(('ebiz_profile_id', '=', self.ebiz_profile_id.id))
        if customer_id is not None:
            domain.append(('ebiz_customer_id', '=', customer_id))
        if internal_id is not None:
            domain.append(('ebiz_internal_id', '=', internal_id))
        return self.env['res.partner'].search(domain)

    def _get_profile_count_customers(self, count_check):
        customers = []
        for instance in self._get_instances():
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
            result = ebiz.client.service.GetPaymentMethodProfileCounts(**{
                'securityToken': ebiz._generate_security_json(),
                'countOnly': False,
                'start': 0,
                'limit': 100000,
            })['PaymentMethodProfileCountsList']['PaymentMethodProfileCounts']
            for method in result:
                if count_check(method):
                    try:
                        local_customer = self._find_local_customer(
                            customer_id=method['CustomerInformation']['CustomerId'])
                        if local_customer:
                            customers.append(local_customer)
                    except Exception:
                        continue
        return customers

    def _search_all_customers(self):
        domain = [('ebiz_internal_id', '!=', False)]
        if self.ebiz_profile_id:
            domain.append(('ebiz_profile_id', '=', self.ebiz_profile_id.id))
        self._apply_customer_lines(self.env['res.partner'].search(domain))

    def _search_no_save_card(self):
        self._apply_customer_lines(
            self._get_profile_count_customers(lambda m: m['CreditCardsCount'] == 0))

    def _search_no_save_back_ach(self):
        self._apply_customer_lines(
            self._get_profile_count_customers(lambda m: m['BankAccountsCount'] == 0))

    def _search_no_payment_method(self):
        self._apply_customer_lines(
            self._get_profile_count_customers(
                lambda m: m['BankAccountsCount'] == 0 and m['CreditCardsCount'] == 0))

    def _search_expired_card(self):
        customers = []
        filters_list = [{'FieldName': 'ExpiredCreditCardsCount', 'ComparisonOperator': 'gt', 'FieldValue': 0}]
        for instance in self._get_instances():
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
            cards = ebiz.client.service.GetCardsExpirationList(**{
                'securityToken': ebiz._generate_security_json(),
                'filters': {"SearchFilter": filters_list},
                'countOnly': False,
                'start': 0,
                'limit': 100000,
                'sort': 'DateTime',
            })['CardExpirationCountsList']
            if cards:
                for card in cards['CardExpirationCounts']:
                    try:
                        local_customer = self._find_local_customer(
                            internal_id=card['CustomerInformation']['CustomerInternalId'])
                        if local_customer:
                            customers.append(local_customer[0])
                    except Exception:
                        continue
        self._apply_customer_lines(customers)

    def _search_card_expiring_soon(self):
        instances = self._get_instances()
        context = {
            'profiles': [self.ebiz_profile_id.id] if self.ebiz_profile_id else instances.ids,
            'payment_method_ui_id': self.id,
        }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Please Select'),
            'res_model': 'wizard.cards.expiring.soon',
            'target': 'new',
            'view_mode': 'form',
            'view_type': 'form',
            'context': context,
        }

    def fetch_pending_payments(self, start, end, instance):
        instances = instance or self.ebiz_profile_id or self.env['ebizcharge.instance.config'].search([('is_valid_credential', '=', True)])
        payment_lines = []
        for instance in instances:
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
            params = {
                'securityToken': ebiz._generate_security_json(),
                'fromPaymentRequestDateTime': str(start),
                'toPaymentRequestDateTime': str(end + timedelta(days=1)),
                "filters": {
                    "SearchFilter": [{
                        'FieldName': 'InvoiceNumber',
                        'ComparisonOperator': 'eq',
                        'FieldValue': 'PM',
                    }]
                },
                "limit": 1000,
                "start": 0,
            }
            payments = ebiz.client.service.SearchEbizWebFormPendingPayments(**params)
            if payments:
                for payment in payments:
                    if payment['CustomerId'].isnumeric():
                        is_customer = self.env['res.partner'].search([('id', '=', int(payment['CustomerId']))])
                        if is_customer:
                            counter = self.env['rpm.counter'].search([('request_id', '=', payment['PaymentInternalId'])])
                            payment_lines.append(fields.Command.create({
                                "customer_id": int(payment['CustomerId']),
                                "email_id": payment['CustomerEmailAddress'],
                                "date_time": datetime.strptime(payment['PaymentRequestDateTime'], '%Y-%m-%dT%H:%M:%S'),
                                "payment_internal_id": payment['PaymentInternalId'],
                                "sync_transaction_id_pending": self.id,
                                'no_of_times_sent': counter.counter if counter else 1,
                            }))
        return payment_lines

    def fetch_received_payments(self, start, end, instance):
        instances = instance or self.ebiz_profile_id or self.env['ebizcharge.instance.config'].search([('is_valid_credential', '=', True)])
        payment_lines = []
        for instance in instances:
            ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
            params = {
                'securityToken': ebiz._generate_security_json(),
                'fromPaymentRequestDateTime': str(start),
                'toPaymentRequestDateTime': str(end + timedelta(days=1)),
                "filters": {
                    "SearchFilter": [{
                        'FieldName': 'InvoiceNumber',
                        'ComparisonOperator': 'eq',
                        'FieldValue': 'PM',
                    }]
                },
                "limit": 1000,
                "start": 0,
            }
            payments = ebiz.client.service.SearchEbizWebFormReceivedPayments(**params)
            if payments:
                for payment in payments:
                    try:
                        if payment['CustomerId'].isnumeric():
                            is_customer = self.env['res.partner'].search([('id', '=', int(payment['CustomerId']))])
                            if is_customer:
                                payment_lines.append(fields.Command.create({
                                    "customer_id": int(payment['CustomerId']),
                                    "email_id": payment['CustomerEmailAddress'],
                                    "date_time": datetime.strptime(payment['PaymentRequestDateTime'], '%Y-%m-%dT%H:%M:%S'),
                                    "payment_internal_id": payment['PaymentInternalId'],
                                    "payment_method": payment['PaymentMethod'] + ' ending in ' + payment['Last4'],
                                    "sync_transaction_id_received": self.id,
                                    "customer_token": is_customer.ebizcharge_customer_token,
                                }))
                    except Exception:
                        pass
        return payment_lines


class ListCustomers(models.TransientModel):
    _name = 'list.ebiz.customers'
    _description = "List Ebiz Customer"

    sync_date = fields.Datetime('Execution Date/Time', required=True, default=fields.Datetime.now)
    sync_transaction_id = fields.Many2one('payment.method.ui', string='Partner Reference', required=True,
                                          ondelete='cascade', index=True, copy=False)
    name = fields.Char(string='Number')
    customer_id = fields.Many2one('res.partner', string='Customer', domain="[('ebiz_customer_id', '!=', False)]")
    email_id = fields.Char(string='Email')
    customer_phone = fields.Char('Phone')
    customer_city = fields.Char('City')
    status = fields.Char(string='Status')

    def view_payment_methods(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Payment Methods',
            'view_mode': 'tree',
            'res_model': 'payment.token',
            'domain': [('partner_id', '=', self.customer_id.id)],
            'context': "{'create': False}",
        }

    def send_request_payment(self):
        try:
            if not self:
                raise UserError('Please select a record first!')
            customer_ids = []
            recipients_obj = self.env['email.recipients']
            recipients_obj.search([]).unlink()
            odoo_customer = self.env['res.partner']
            for record in self:
                recipient = recipients_obj.create({
                    'partner_id': record.customer_id.id,
                    'email': record.email_id,
                })
                customer_ids.append(recipient.id)
                odoo_customer = record.customer_id
                if odoo_customer and odoo_customer.customer_rank > 0 and not odoo_customer.ebiz_internal_id:
                    odoo_customer.sync_to_ebiz()
            profile = odoo_customer.ebiz_profile_id.id if odoo_customer and odoo_customer.ebiz_profile_id else False
            return {
                'type': 'ir.actions.act_window',
                'name': _('Request Payment Method'),
                'res_model': 'wizard.ebiz.request.payment.method.bulk',
                'target': 'new',
                'view_mode': 'form',
                'views': [[False, 'form']],
                'context': {
                    'default_partner_id': [fields.Command.set(customer_ids)],
                    'selection_check': 1,
                    'customers': customer_ids,
                    'default_ebiz_profile_id': profile,
                    'profile': profile,
                },
            }
        except Exception as e:
            raise UserError(e)


class ListPendingMethods(models.Model):
    _name = 'list.pending.payments.methods'
    _description = "List Pending Payment Methods"

    sync_date = fields.Datetime('Execution Date/Time', required=True, default=fields.Datetime.now)
    sync_transaction_id_pending = fields.Many2one('payment.method.ui', string='Partner Reference', required=True,
                                                  ondelete='cascade', index=True, copy=False)
    name = fields.Char(string='Number')
    customer_id = fields.Many2one('res.partner', string='Customer', domain="[('ebiz_customer_id', '!=', False)]")
    email_id = fields.Char(string='Email')
    date_time = fields.Datetime(string='Org. Date & Time Sent')
    payment_internal_id = fields.Char(string='Payment Internal Id')
    no_of_times_sent = fields.Integer("# of Times Sent")

    def resend_email(self):
        try:
            if not self:
                raise UserError('Please select a record first!')
            resp_lines = []
            success = 0
            failed = 0
            total_count = len(self)
            ebiz_obj = self.env['ebiz.charge.api']
            rpm_counter_obj = self.env['rpm.counter']
            for record in self:
                resp_line = {
                    'customer_name': record.customer_id.id,
                    'customer_id': record.customer_id.id,
                    'email_address': record.email_id,
                }
                instance = record.customer_id.ebiz_profile_id or None
                ebiz = ebiz_obj.get_ebiz_charge_obj(instance=instance)
                ebiz.client.service.ResendEbizWebFormEmail(**{
                    'securityToken': ebiz._generate_security_json(),
                    'paymentInternalId': record.payment_internal_id,
                })
                counter = rpm_counter_obj.search([('request_id', '=', record.payment_internal_id)])
                if counter:
                    counter[0].counter += 1
                else:
                    counter = rpm_counter_obj.create({'counter': 1, 'request_id': record.payment_internal_id})
                record.no_of_times_sent = counter[0].counter
                resp_line['status'] = 'Success'
                success += 1
                resp_lines.append(fields.Command.create(resp_line))

            wizard = self.env['wizard.multi.payment.message'].create({
                'name': 'resend',
                'lines_ids': resp_lines,
                'success_count': success,
                'failed_count': failed,
                'total': total_count,
            })
            return {
                'type': 'ir.actions.act_window',
                'name': _('Request Payment Methods'),
                'res_model': 'wizard.multi.payment.message',
                'target': 'new',
                'res_id': wizard.id,
                'view_mode': 'form',
                'views': [[False, 'form']],
                'context': self.env.context,
            }
        except Exception as e:
            raise UserError(e)

    def delete_invoice(self):
        try:
            if not self:
                raise UserError('Please select a record first!')
            text = f"Are you sure you want to remove {len(self)} request(s) from Pending Requests?"
            wizard = self.env['wizard.delete.payment.methods'].create({
                "record_id": self[0].sync_transaction_id_pending.id,
                "record_model": self._name,
                "text": text,
            })
            action = self.env.ref('payment_ebizcharge_crm.wizard_delete_rpm_action').read()[0]
            action['res_id'] = wizard.id
            action['context'] = dict(
                self.env.context,
                selected_line_ids=self.ids,
                pending_received='Pending Requests',
            )
            return action
        except Exception as e:
            raise UserError(e)


class ListReceivedMethods(models.Model):
    _name = 'list.received.payments.methods'
    _description = "List Received Payment Methods"

    sync_date = fields.Datetime('Execution Date/Time', required=True, default=fields.Datetime.now)
    sync_transaction_id_received = fields.Many2one('payment.method.ui', string='Partner Reference', required=True,
                                                   ondelete='cascade', index=True, copy=False)
    customer_id = fields.Many2one('res.partner', string='Customer', domain="[('ebiz_customer_id', '!=', False)]")
    email_id = fields.Char(string='Email')
    date_time = fields.Datetime(string='Date & Time Added')
    payment_internal_id = fields.Char(string='Payment Internal Id')
    payment_method = fields.Char('Payment Method')
    customer_token = fields.Char('Customer Token')

    def delete_invoice_added(self):
        try:
            if not self:
                raise UserError('Please select a record first!')
            text = f"Are you sure you want to remove {len(self)} payment method(s) from Added Payment Methods?"
            wizard = self.env['wizard.delete.payment.methods'].create({
                "record_id": self[0].sync_transaction_id_received.id,
                "record_model": self._name,
                "text": text,
            })
            action = self.env.ref('payment_ebizcharge_crm.wizard_delete_rpm_action').read()[0]
            action['res_id'] = wizard.id
            action['context'] = dict(
                self.env.context,
                selected_line_ids=self.ids,
                pending_received='Added Payment Methods',
            )
            return action
        except Exception as e:
            raise UserError(e)
