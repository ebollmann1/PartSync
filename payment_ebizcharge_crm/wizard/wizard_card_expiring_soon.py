from odoo import fields, models, api, _
from odoo.exceptions import UserError, ValidationError
import logging


class CardExpiringSoon(models.TransientModel):
    _name = 'wizard.cards.expiring.soon'
    _description = "Wizard Cards Expiring Soon"

    date_selection = fields.Selection([
        ('this_month', 'This month'),
        ('next_month', 'Next month'),
        ('within_3_month', 'Within 3 months'),
        ('within_6_month', 'Within 6 months'),
        ('within_a_year', 'Within a year'),
    ], string='Display customers with saved card(s) expiring', help="Select specific time you'd like to display", default='this_month')

    no_of_days = fields.Integer('Within days')

    def apply_filters(self):
        try:
            instances = self.env['ebizcharge.instance.config'].browse(self.env.context.get('profiles'))
            payment_ui = self.env['payment.method.ui'].browse(self.env.context.get('payment_method_ui_id'))
            line_vals = [fields.Command.clear()]
            for instance in instances:
                filters_list = []
                ebiz = self.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)

                _filter_map = {
                    'this_month': 'ExpireThisMonthCreditCardsCount',
                    'next_month': 'ExpireNextMonthCreditCardsCount',
                    'within_3_month': 'ExpireWithin3MonthCreditCardsCount',
                    'within_6_month': 'ExpireWithin6MonthCreditCardsCount',
                    'within_a_year': 'ExpireWithinaYearCreditCardsCount',
                    'specific_days': 'ExpireWithinaYearCreditCardsCount',
                }
                field_name = _filter_map.get(self.date_selection)
                if not field_name:
                    raise UserError('No option selected!')
                filters_list.append({'FieldName': field_name, 'ComparisonOperator': 'gt', 'FieldValue': 0})

                params = {
                    'securityToken': ebiz._generate_security_json(),
                    'filters': {"SearchFilter": filters_list},
                    'countOnly': False,
                    'start': 0,
                    'limit': 100000,
                    'sort': 'DateTime'
                }
                cards = ebiz.client.service.GetCardsExpirationList(**params)['CardExpirationCountsList']
                if cards:
                    cards_lists = cards['CardExpirationCounts']

                    for card in cards_lists:
                        try:
                            internal_id = card['CustomerInformation']['CustomerInternalId']
                            if not internal_id:
                                continue
                            local_customer = self.env['res.partner'].search(
                                [('ebiz_internal_id', '=', internal_id)], limit=1)
                        except Exception:
                            continue

                        if local_customer:
                            line_vals.append(fields.Command.create({
                                'customer_id': local_customer.id,
                                'email_id': card['CustomerInformation']['Email'] or '',
                                'customer_phone': card['CustomerInformation']['Phone'] or '',
                                'customer_city': card['CustomerInformation']['BillingAddress'] or
                                                 card['CustomerInformation']['ShippingAddress'] or '',
                                'sync_transaction_id': payment_ui.id,
                            }))

            payment_ui.transaction_history_line = line_vals
        except Exception as e:
            raise ValidationError(e)
