from odoo.http import request

from odoo.addons.payment.controllers import portal as payment_portal
from odoo.addons.portal.controllers import portal


class CustomerPortal(portal.CustomerPortal):

    def getTransactionData(self, order):
        filters_list = []
        transaction_history = request.env['transaction.header'].sudo()
        filters_list.append((transaction_history.sudo()._get_filter_object('OrderID', 'eq', order.name)))
        transactions = transaction_history.get_instance_transaction(filters=filters_list, ebiz_profile=order.partner_id.ebiz_profile_id)
        return transactions


class PaymentPortal(payment_portal.PaymentPortal):

    def _get_payment_values(self, order_sudo, downpayment=False, **kwargs):
        logged_in = not request.env.user._is_public()
        partner_sudo = request.env.user.partner_id if logged_in else order_sudo.partner_id
        company = order_sudo.company_id
        if downpayment:
            amount = order_sudo._get_prepayment_required_amount()
        else:
            amount = order_sudo.amount_total - order_sudo.amount_paid
        currency = order_sudo.currency_id

        providers_sudo = request.env['payment.provider'].sudo()._get_compatible_providers(
            company.id,
            partner_sudo.id,
            amount,
            currency_id=currency.id,
            sale_order_id=order_sudo.id,
            **kwargs,
        )
        payment_methods_sudo = request.env['payment.method'].sudo()._get_compatible_payment_methods(
            providers_sudo.ids,
            partner_sudo.id,
            currency_id=currency.id,
        )
        tokens_sudo = request.env['payment.token'].sudo()._get_available_tokens(
            providers_sudo.ids, partner_sudo.id, **kwargs
        )

        company_mismatch = not payment_portal.PaymentPortal._can_partner_pay_in_company(
            partner_sudo, company
        )

        portal_page_values = {
            'company_mismatch': company_mismatch,
            'expected_company': company,
        }
        payment_form_values = {
            'show_tokenize_input_mapping': PaymentPortal._compute_show_tokenize_input_mapping(
                providers_sudo, sale_order_id=order_sudo.id
            ),
        }
        ebiz_provider_enabled = providers_sudo.filtered(lambda x: x.code == 'ebizcharge' and x.state == 'enabled')
        if ebiz_provider_enabled:
            is_sur_able = False
            showACH = False
            showCreditCards = False
            cardNarrations = False
            authOnly = False
            if request.env.user.partner_id.ebiz_profile_id:
                profile = request.env.user.partner_id.ebiz_profile_id
            else:
                profile = request.env['ebizcharge.instance.config'].sudo().search(
                    [('website_ids', 'in', request.website.ids), ('is_website', '=', True)], limit=1)
            if profile:
                showACH = profile.merchant_data
                showCreditCards = profile.allow_credit_card_pay
                allowedCommands = profile.ebiz_website_allowed_command
                authOnly = allowedCommands == 'pre-auth'
                is_sur_able = False
                if profile.is_surcharge_enabled and profile.surcharge_type_id == 'DailyDiscount':
                    is_sur_able = True
                cardNarrations = profile.surcharge_terms
            payment_context = {
                'showACH': showACH,
                'showCreditCards': showCreditCards,
                'cardNarrations': cardNarrations,
                'surcharge_terms': cardNarrations,
                'is_sur_able': is_sur_able,
                'authOnly': authOnly,
                'logIn': bool(request.session['session_token']),
                'tokens': request.env['payment.token'].sudo().search(
                    [('provider_id', 'in', providers_sudo.filtered(lambda i: i.code != 'ebizcharge').ids),
                     ('partner_id', '=', partner_sudo.id)]),
                'amount': amount,
                'currency': currency,
                'partner_id': partner_sudo.id,
                'providers_sudo': providers_sudo,
                'providers_sudo_ebiz': providers_sudo.filtered(lambda i: i.code == "ebizcharge"),
                'payment_methods_sudo': payment_methods_sudo,
                'tokens_sudo': tokens_sudo.filtered(lambda i: i.provider_id.code != 'ebizcharge'),
                'ebiz_tokens': tokens_sudo.filtered(lambda i: i.provider_id.code == 'ebizcharge'),
                'transaction_route': order_sudo.get_portal_url(suffix='/transaction'),
                'landing_route': order_sudo.get_portal_url(),
                'access_token': order_sudo._portal_ensure_token(),
            }
            return {
                **portal_page_values,
                **payment_form_values,
                **payment_context,
                **self._get_extra_payment_form_values(**kwargs),
            }
        else:
            return super()._get_payment_values(order_sudo, downpayment=False, **kwargs)
