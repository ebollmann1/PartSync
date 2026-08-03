from odoo import _, http
from odoo.http import request
from odoo.addons.portal.controllers import portal


class PaymentPortal(portal.CustomerPortal):
    @http.route(['/payment/ebizcharge/manage/token'], type='jsonrpc', auth='public', methods=["POST"], csrf=False)
    def ebizcharge_get_token_manage(self, pm_id):
        return request.env['payment.token'].get_payment_token_information(pm_id)


class EbizCustomerPortal(http.Controller):

    @http.route('/my/ebiz_payment_method', type="http", website=True, auth='user')
    def ebiz_payment_method_content(self, **kw):
        if request.env.user.partner_id.ebiz_profile_id:
            profile = request.env.user.partner_id.ebiz_profile_id
        else:
            profile = request.env['ebizcharge.instance.config'].sudo().search(
                [('website_ids', 'in', request.website.ids), ('is_website', '=', True), ('is_active', '=', True)], limit=1)
        verify_card_before_saving = ''
        show_ach = False
        show_credit_cards = False
        auth_only = False
        payment_tokens = request.env['payment.token']
        if profile:
            show_ach = profile.merchant_data
            show_credit_cards = profile.allow_credit_card_pay
            auth_only = profile.ebiz_website_allowed_command == 'pre-auth'
            if profile.verify_card_before_saving:
                verify_card_before_saving = 'true'
            odoo_partner = request.env.user.partner_id
            # odoo_partner.sudo().with_context(
            #     {'donot_sync': True, 'website': request.website.id}).ebiz_get_payment_methods()
            payment_tokens = odoo_partner.payment_token_ids
            payment_tokens |= odoo_partner.commercial_partner_id.sudo().payment_token_ids
        provider_id = request.env['payment.provider'].sudo().search(
            [('code', '=', 'ebizcharge'), ('company_id', '=', request.env.company.id)], limit=1).id
        values = {
            'logIn': bool(request.session['session_token']),
            'showACH': show_ach,
            'showCreditCards': show_credit_cards,
            'authOnly': auth_only,
            'VerifyCreditCardBeforeSaving': verify_card_before_saving,
            'id': provider_id,
            'providerid': provider_id,
            'tokens': payment_tokens,
        }
        return request.render('payment_ebizcharge_portal.payment_methods', values)
