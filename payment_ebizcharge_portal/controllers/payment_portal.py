from odoo.http import request
from odoo.addons.account.controllers import portal
from odoo.addons.payment.controllers.portal import PaymentPortal

class PortalAccount(portal.PortalAccount, PaymentPortal):

    def _invoice_get_page_view_values(self, invoice, access_token, **kwargs):
        values = super()._invoice_get_page_view_values(invoice, access_token, **kwargs)

        if not invoice._has_to_be_paid():
            return values

        logged_in = not request.env.user._is_public()
        partner_sudo = request.env.user.partner_id if logged_in else invoice.partner_id
        invoice_company = invoice.company_id or request.env.company

        providers_sudo = request.env['payment.provider'].sudo()._get_compatible_providers(
            invoice_company.id,
            partner_sudo.id,
            invoice.amount_total,
            currency_id=invoice.currency_id.id
        )
        payment_methods_sudo = request.env['payment.method'].sudo()._get_compatible_payment_methods(
            providers_sudo.ids,
            partner_sudo.id,
            currency_id=invoice.currency_id.id,
        )
        tokens_sudo = request.env['payment.token'].sudo()._get_available_tokens(
            providers_sudo.ids, partner_sudo.id
        )

        company_mismatch = not PaymentPortal._can_partner_pay_in_company(
            partner_sudo, invoice_company
        )

        portal_page_values = {
            'company_mismatch': company_mismatch,
            'expected_company': invoice_company,
        }
        payment_form_values = {
            'show_tokenize_input_mapping': PaymentPortal._compute_show_tokenize_input_mapping(
                providers_sudo
            ),
        }
        ebiz_provider_enabled = providers_sudo.filtered(lambda x: x.code == 'ebizcharge' and x.state != 'disabled')
        if ebiz_provider_enabled:
            payment_context = {
                'ebiz_tokens': request.env['payment.token'].sudo().search(
                    [('provider_id', 'in', providers_sudo.filtered(lambda i: i.code == "ebizcharge").ids), ('partner_id', '=', partner_sudo.id)]),
                'tokens': request.env['payment.token'].sudo().search(
                    [('provider_id', 'in', providers_sudo.filtered(lambda i: i.code != "ebizcharge").ids), ('partner_id', '=', partner_sudo.id)]),
                'amount': invoice.amount_residual,
                'currency': invoice.currency_id,
                'partner_id': partner_sudo.id,
                'providers_sudo': providers_sudo,
                'providers_ebiz': providers_sudo.filtered(lambda i: i.code == "ebizcharge"),
                'payment_methods_sudo': payment_methods_sudo,
                'tokens_sudo': tokens_sudo.filtered(lambda i: i.provider_id.code != 'ebizcharge'),
                'transaction_route': f'/invoice/transaction/{invoice.id}/',
                'landing_route': invoice.get_portal_url(),
                'access_token': access_token,
            }
            values.update(
                **portal_page_values,
                **payment_form_values,
                **payment_context,
                **self._get_extra_payment_form_values(**kwargs),
            )
            return values
        else:
            return super()._invoice_get_page_view_values(invoice, access_token, **kwargs)
