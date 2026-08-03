from werkzeug.exceptions import BadRequest

from odoo import http, _
from odoo.http import request
from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.addons.payment.controllers.post_processing import PaymentPostProcessing


class EbizWebsitePayment(CustomerPortal):

    def _prepare_portal_layout_values(self):
        values = super()._prepare_portal_layout_values()
        ebizcharge_active = bool(request.env['payment.provider'].sudo().search([
            ('code', '=', 'ebizcharge'),
            ('state', 'not in', ['disabled']),
            ('company_id', '=', request.env.company.id),
        ], limit=1))
        has_other_providers = bool(request.env['payment.provider'].sudo().search([
            ('code', '!=', 'ebizcharge'),
            ('state', 'not in', ['disabled']),
            ('company_id', '=', request.env.company.id),
        ], limit=1))
        values['ebizcharge_active'] = ebizcharge_active
        values['has_other_providers'] = has_other_providers
        return values

    @http.route('/payment/pay', type='http', methods=['GET'], auth='public', website=True, sitemap=False)
    def payment_pay(self, reference=None, amount=None, currency_id=None, partner_id=None, company_id=None,
                    provider_id=None, access_token=None, invoice_id=None, **kwargs):

        res = super().payment_pay(reference=reference, amount=amount, currency_id=currency_id,
                                  partner_id=partner_id, company_id=company_id,
                                  provider_id=provider_id, access_token=access_token,
                                  invoice_id=invoice_id, custom_create_values={'invoice_ids': [Command.set([invoice_id])]}, **kwargs)
        if invoice_id:
            inv = request.env['account.move'].sudo().search([('id', '=', int(invoice_id))])
            inv.partner_id.refresh_payment_methods()
        if res.status_code == 200:
            odooInvoice = request.env['account.move'].sudo().search([('name', '=', reference),
                                                                     ('payment_state', '=', 'paid')])
            if odooInvoice and odooInvoice.partner_id.ebiz_profile_id:
                return request.render("payment_ebizcharge_crm.payment_already_paid")

        if res and 'tokens_sudo' in res.qcontext and 'providers_sudo' in res.qcontext:
            payment_tokens = res.qcontext['tokens_sudo']
            ebiz_payment_tokens = request.env['payment.token'].sudo().search([
                ('partner_id', '=', request.env.user.partner_id.id), ('provider_code', '=', "ebizcharge"),
                ('company_id', '=', request.env.user.company_id.id)
            ])
            res.qcontext['providers_ebiz'] = res.qcontext['providers_sudo'].filtered(lambda i: i.code == "ebizcharge")
            res.qcontext['tokens_sudo'] = payment_tokens.sudo().filtered(
                lambda r: r.provider_id.code != "ebizcharge")
            res.qcontext['ebiz_tokens'] = ebiz_payment_tokens
        return res

    def _get_extra_payment_form_values(self, **kwargs):
        rendering_context_values = super()._get_extra_payment_form_values(**kwargs)
        ebiz_providers = request.env['payment.provider'].sudo().search(
            [('code', '=', 'ebizcharge'), ('company_id', '=', request.env.user.company_id.id),
             ('state', '!=', 'disabled')])
        profile = False
        if ebiz_providers:
            if request.env.user.partner_id.ebiz_profile_id and not request.env.user._is_public():
                profile = request.env.user.partner_id.ebiz_profile_id
            elif 'invoice_id' in rendering_context_values:
                inv_load = request.env['account.move'].sudo().search([('id', '=', rendering_context_values['invoice_id'])], limit=1)
                if inv_load:
                    profile = inv_load.partner_id.ebiz_profile_id
                    if not profile:
                        profile = request.env['ebizcharge.instance.config'].sudo().search(
                            [('website_ids', 'in', request.website.ids), ('is_website', '=', True), ('is_active', '=', True)], limit=1)
            else:
                profile = request.env['ebizcharge.instance.config'].sudo().search(
                    [('website_ids', 'in', request.website.ids), ('is_website', '=', True), ('is_active', '=', True)], limit=1)
            if profile:
                showACH = profile.merchant_data
                showCreditCards = profile.allow_credit_card_pay
                allowedCommands = profile.ebiz_website_allowed_command
                authOnly = allowedCommands == 'pre-auth'
                rendering_context_values['logIn'] = bool(request.session['session_token'])
                is_sur_able = False
                surcharge_terms = ''
                if profile.is_surcharge_enabled and profile.surcharge_type_id == 'DailyDiscount':
                    is_sur_able = True
                    surcharge_terms = profile.surcharge_terms

                rendering_context_values['surcharge_terms'] = surcharge_terms
                rendering_context_values['is_sur_able'] = is_sur_able
                rendering_context_values['showACH'] = showACH
                rendering_context_values['showCreditCards'] = showCreditCards
                rendering_context_values['authOnly'] = authOnly
        return rendering_context_values


class TransactionPortal(CustomerPortal):

    @http.route(['/my/orders/<int:order_id>'], type='http', auth="public", website=True)
    def portal_order_page(self, order_id, report_type=None, access_token=None, message=False, download=False, **kw):
        res = super().portal_order_page(order_id, report_type=report_type,
                                        access_token=access_token, message=message,
                                        download=download, **kw)
        if res.status_code == 200:
            ebiz_charge_transaction = request.env['sale.order'].sudo().browse(order_id).transaction_ids.filtered(lambda x: x.provider_code == 'ebizcharge')
            if ebiz_charge_transaction:
                transaction_obj = request.env['transaction.history']
                if 'sale_order' in res.qcontext:
                    if 'search' in kw and kw['search'] != "":
                        transactions = transaction_obj.sudo().search([('invoice_id', '=', res.qcontext['sale_order'].name)])
                        if not transactions:
                            response = self.getTransactionData(res.qcontext['sale_order'])
                            transaction_obj.sudo().search([]).unlink()
                            transaction_obj.sudo().create(response)
                            transactions = transaction_obj.sudo().search([('invoice_id', '=', res.qcontext['sale_order'].name)])
                        transactions = transactions.sudo().search([('ref_no', '=', kw['search'])])
                    else:
                        response = self.getTransactionData(res.qcontext['sale_order'])
                        transaction_obj.sudo().search([]).unlink()
                        transaction_obj.sudo().create(response)
                        transactions = transaction_obj.sudo().search([('invoice_id', '=', res.qcontext['sale_order'].name)])
                    res.qcontext.update({
                        'transactions': transactions,
                    })
        return res


class PaymentPortal(CustomerPortal):

    def _create_transaction(
            self, provider_id, payment_method_id, token_id, amount, currency_id, partner_id, flow,
            tokenization_requested, landing_route, reference_prefix=None, is_validation=False, token_ebiz=None,
            custom_create_values=None, **kwargs
    ):
        if token_id and not provider_id:
            token_sudo = request.env['payment.token'].sudo().browse(token_id)
            provider_id = token_sudo.provider_id.id

        if request.env['payment.provider'].sudo().browse(provider_id).code != 'ebizcharge':
            return super()._create_transaction(
                provider_id, payment_method_id, token_id, amount, currency_id, partner_id, flow,
                tokenization_requested, landing_route, reference_prefix=reference_prefix,
                is_validation=is_validation, custom_create_values=custom_create_values, **kwargs
            )

        if flow == 'direct' and not request.env.user._is_public() and token_id:
            token_ebiz = None
            flow = 'token'
        if flow in ['redirect', 'direct']:
            provider_sudo = request.env['payment.provider'].sudo().browse(provider_id)
            token_id = None
            tokenize = bool(
                provider_sudo.allow_tokenization
                and (provider_sudo._is_tokenization_required(**kwargs) or tokenization_requested)
            )
        elif flow == 'token':
            token_sudo = request.env['payment.token'].sudo().browse(token_id)
            if token_sudo.partner_id:
                partner_id = token_sudo.partner_id.id
            partner_sudo = request.env['res.partner'].sudo().browse(partner_id)
            provider_sudo = token_sudo.provider_id
            payment_method_id = token_sudo.payment_method_id.id
            tokenize = False
        else:
            raise ValidationError(
                _("The payment should either be direct, with redirection, or made by a token.")
            )

        reference = request.env['payment.transaction']._compute_reference(
            provider_sudo.code,
            prefix=reference_prefix,
            **(custom_create_values or {}),
            **kwargs
        )
        if is_validation:
            amount = provider_sudo._get_validation_amount()
            currency_id = provider_sudo._get_validation_currency().id

        tx_sudo = request.env['payment.transaction'].sudo().create({
            'provider_id': provider_sudo.id,
            'payment_method_id': payment_method_id,
            'reference': reference,
            'amount': amount,
            'currency_id': currency_id,
            'partner_id': partner_id,
            'token_id': token_id,
            'operation': f'online_{flow}' if not is_validation else 'validation',
            'tokenize': tokenize,
            'landing_route': landing_route,
            **(custom_create_values or {}),
        })

        if flow == 'token' and not request.env.context.get('delay_payment_request'):
            if 'web_pay' in kwargs:
                tx_sudo.with_context({'web_pay': kwargs['web_pay'], 'from_portal': True})._send_payment_request()
            else:
                tx_sudo.sudo().write({'transaction_type': 'pre_auth'})
                tx_sudo.with_context({'set_done': True, 'from_portal': True, 'web_pay': '1'})._send_payment_request()
        else:
            # Save path (flow='token' + delay_payment_request) must not fire SOAP here;
            # shop_payment_transaction will call _send_payment_request separately.
            token_ebiz_for_log = None if request.env.context.get('delay_payment_request') else token_ebiz
            tx_sudo.with_context(
                {'set_done': True, 'from_portal': True, 'web_pay': '1', 'run_transaction': '1', 'token_ebiz': token_ebiz_for_log})._log_sent_message(
                token_ebiz=token_ebiz_for_log)

        PaymentPostProcessing.monitor_transaction(tx_sudo)
        new_token = request.env['payment.token'].sudo().search([('id', '=', token_id)], limit=1)
        if new_token and not new_token.is_card_save:
            new_token.delete_payment_method()
            partner = request.env['res.partner'].sudo().browse(partner_id)
            partner.refresh_payment_methods()

        return tx_sudo

    @staticmethod
    def _validate_transaction_kwargs(kwargs, additional_allowed_keys=()):
        whitelist = {
            'provider_id',
            'payment_method_id',
            'token_id',
            'amount',
            'flow',
            'tokenization_requested',
            'landing_route',
            'is_validation',
            'token_ebiz',
            'csrf_token',
        }
        whitelist.update(additional_allowed_keys)
        rejected_keys = set(kwargs.keys()) - whitelist
        if rejected_keys:
            raise BadRequest(
                _("The following kwargs are not whitelisted: %s", ', '.join(rejected_keys))
            )

    def validate_card_runcustomertransaction(self, partner, token):
        try:
            instance = partner.ebiz_profile_id
            ebiz = request.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=instance)
            params = {
                "securityToken": ebiz._generate_security_json(),
                "custNum": partner.ebizcharge_customer_token,
                "paymentMethodID": token.ebizcharge_profile,
                "tran": {
                    "isRecurring": False,
                    "IgnoreDuplicate": False,
                    "Details": self.transaction_details(),
                    "Software": 'Odoo CRM',
                    "MerchReceipt": True,
                    "CustReceiptName": '',
                    "CustReceiptEmail": '',
                    "CustReceipt": False,
                    "Command": 'AuthOnly',
                },
            }
            resp = ebiz.client.service.runCustomerTransaction(**params)
            resp_void = ebiz.execute_transaction(resp['RefNum'], {'command': 'Void'})
        except Exception as e:
            raise ValidationError(e)
        return resp

    def transaction_details(self):
        return {
            'OrderID': "Token",
            'Invoice': "Token",
            'PONum': "Token",
            'Description': 'description',
            'Amount': 0.05,
            'Tax': 0,
            'Shipping': 0,
            'Discount': 0,
            'Subtotal': 0.05,
            'AllowPartialAuth': False,
            'Tip': 0,
            'NonTax': True,
            'Duty': 0
        }
