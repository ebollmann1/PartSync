/** @odoo-module **/

import { Component } from '@odoo/owl';
import publicWidget from '@web/legacy/js/public/public_widget';
import { ConfirmationDialog } from '@web/core/confirmation_dialog/confirmation_dialog';
import { _t } from '@web/core/l10n/translation';
import { rpc, RPCError } from "@web/core/network/rpc";

const FIELD_ERROR_MESSAGES = {
    'confirm-account-number': "Account number does not match.",
    'confirm-routing-number': "Routing number does not match.",
    'account-number': "Enter a 4-17 digit account number.",
    'routing-number': "Enter a 9 digit routing number.",
    'bank_account_holder_name': "Enter a valid account holder name.",
    'bank-account-type': "Select a valid account type.",
    'cc_holder_name': "Enter a valid cardholder name.",
    'card_number': "Enter a valid 13-19 digit card number.",
    'avs-street': "Enter a valid billing address.",
    'cc-expiry': "Enter a valid expiration date.",
    'cc-cvc': "Enter a valid CVC.",
    'zip-code': "Enter a valid 5–9 character zip/postal code.",
};

publicWidget.registry.eBizPaymentForm = publicWidget.Widget.extend({
    selector: '#o_ebiz_payment_form',
    events: Object.assign({}, publicWidget.Widget.prototype.events, {
        'click [name="ebiz_submit_button"]': '_ebizSubmitButton',
        'click [name="ebiz_cancel_button"]': '_ebizCancelButton',
        'click [name="update_ebiz_card"]': '_updateEbizCard',
        'click [name="update_ebiz_account"]': '_updateEbizAccount',
        'click #card-tab': '_addNewEbizCard',
        'click #account-tab': '_addNewEbizAccount',
        'click button[name="delete_ebiz_pm"]': '_deletePmEvent',
        'click button[name="refresh_payment_tokens"]': '_refreshPaymentMethods',
        'click button[name="show_hide_tokens"]': '_showHideTokens',
    }),


    // #=== WIDGET LIFECYCLE ===#

    init() {
        this._super(...arguments);
        this.orm = this.bindService("orm");
    },

    _displayErrorDialog(title, errorMessage = '') {
        this.call('dialog', 'add', ConfirmationDialog, { title, body: errorMessage });
    },

    _deletePmEvent(ev) {
        const recordId = parseInt(ev.currentTarget.value);
        debugger;
        this.call("dialog", "add", ConfirmationDialog, {
            title: _t("Delete Record"),
            body: _t("Are you sure you want to delete this record?"),
            confirmLabel: _t("Delete"),
            confirm: async () => {
                this._disableButton(true);
                try {
                    const response = await rpc('/delete/ebizcharge/token', { pm_id: recordId });
                    if (response === 'success') {
                        window.location = '/my/ebiz_payment_method';
                    } else {
                        this._displayErrorDialog(_t("Not Found Error"), response);
                        this._disableButton(false);
                    }
                } catch (error) {
                    if (error instanceof RPCError) {
                        this._displayErrorDialog(_t("Payment processing failed"), error.data.message);
                    }
                    this._disableButton(false);
                }
            },
            cancel: () => {},
        });
    },

    _disableButton(blockUI = false) {
        Component.env.bus.trigger('disablePaymentButton');
        if (blockUI) {
            this.call('ui', 'block');
        }
    },

    _enableButton(unblockUI = true) {
        Component.env.bus.trigger('enablePaymentButton');
        if (unblockUI) {
            this.call('ui', 'unblock');
        }
    },

    _ebizCancelButton() {
        window.location = '/my/ebiz_payment_method';
    },

    async _ebizSubmitButton() {
        const providerId = document.getElementById('ebiz_provider_id').value;
        const paymentDetails = await this._getPaymentDetails(providerId);
        if (!paymentDetails) return;
        const button = document.getElementById('add_new_ebiz_card');
        button.disabled = true;
        try {
            const result = await rpc('/payment/ebizcharge/s2s/create_json_3ds', { kwargs: paymentDetails });
            if (result) {
                window.location = '/my/ebiz_payment_method';
            }
        } catch (error) {
            if (error instanceof RPCError) {
                this._displayErrorDialog(_t("Payment processing failed"), error.data.message);
            }
            button.disabled = false;
        }
    },

    _showHideTokens() {
        ['CreditCards', 'CreditCardsDetails', 'BankAccounts', 'BankAccountsDetails'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
        });
    },

    async _refreshPaymentMethods(ev) {
        if (this._refreshing) return;
        this._refreshing = true;
        const btn = ev.currentTarget;
        const originalHtml = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span> Refreshing...';
        try {
            await rpc('/refresh_payment_profiles');
            location.reload();
        } catch (error) {
            if (error instanceof RPCError) {
                this._displayErrorDialog(_t("Refresh failed"), error.data.message);
            }
            this._refreshing = false;
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }
    },

    _getAcquirerTypeFromCheckbox(element) {
        return element?.[0]?.id;
    },

    _getInlineFormInputs(acquirerId) {
        const acquirerType = document.getElementById('new_account_tab_id').value;
        if (acquirerType === 'new_account' || acquirerType === 'update_account') {
            return {
                accountName: document.getElementById('bank_account_holder_name'),
                accountNumber: document.getElementById('account_number'),
                routingNumber: document.getElementById('routing_number'),
                tokenAccBox: document.getElementById('token_save_box_acc'),
                accountType: document.getElementById('bank_account_type'),
                pmid: document.getElementById('update_pm_id'),
                default_card_method: document.getElementById('default_card_method'),
                ismanageScreen: document.getElementById('is_ebiz_manage_screen'),
            };
        }
        return {
            card: document.getElementById('cc_number'),
            name: document.getElementById('cc_holder_name'),
            street: document.getElementById('avs_street'),
            zip: document.getElementById('avs_zip'),
            expiry: document.getElementById('cc_expiry'),
            tokenBox: document.getElementById('token_save_box_credit'),
            code: document.getElementById('cc_cvc'),
            pmid: document.getElementById('update_pm_id'),
            default_card_method: document.getElementById('default_card_method'),
            ismanageScreen: document.getElementById('is_ebiz_manage_screen'),
        };
    },

    _addNewEbizCard() {
        document.getElementById('new_account_tab_id').value = "new_card";
    },

    _addNewEbizAccount() {
        document.getElementById('new_account_tab_id').value = "new_account";
    },

    _getErrorMessage(element) {
        const $group = $(element).closest('div.form-group');
        for (const [cls, msg] of Object.entries(FIELD_ERROR_MESSAGES)) {
            if ($group.hasClass(cls)) return msg;
        }
        return "The value is invalid.";
    },

    _validateFormInputs(selector) {
        const elements = $('input, select', selector).toArray();
        let hasError = false;
        for (const element of elements) {
            if ($(element).attr('type') === 'hidden') continue;
            const $group = $(element).closest('div.form-group');
            $group.removeClass('o_has_error').find('.form-control, .custom-select').removeClass('is-invalid');
            $(element).siblings('.o_invalid_field').remove();
            $(element).trigger("focusout");

            let message = null;
            if ((element.dataset.isRequired && element.value.length === 0) || $group.hasClass('o_has_error')) {
                message = this._getErrorMessage(element);
            } else if ($group.hasClass('confirm-account-number') && $('#confirm_account_number').val() !== $('#account_number').val()) {
                message = "Account number does not match.";
            } else if ($group.hasClass('confirm-routing-number') && $('#confirm_routing_number').val() !== $('#routing_number').val()) {
                message = "Routing number does not match.";
            }

            if (message) {
                $group.addClass('o_has_error').find('.form-control, .custom-select').addClass('is-invalid');
                $group.append(`<div style="color: red" class="o_invalid_field" aria-invalid="true">${message}</div>`);
                hasError = true;
            }
        }
        return !hasError;
    },

    async _getPaymentDetails(acquirerId) {
        const inputs = this._getInlineFormInputs(acquirerId);
        const acquirerType = document.getElementById('new_account_tab_id').value;
        const checkdefault = document.querySelector('.default_check:checked') ? 'true' : 'false';
        const updatePmId = document.getElementById('update_pm_id').value;

        if (acquirerType === 'new_account' || acquirerType === 'update_account') {
            if (!this._validateFormInputs('#addBankAccountDetails')) return;
            const tokenBoxValsAch = document.querySelector('.token_box_ach_vals:checked') || inputs.tokenAccBox?.value === 'True'
                ? 'true' : 'false';
            return {
                acquirer_id: acquirerId,
                provider_id: acquirerId,
                update_pm_id: updatePmId,
                is_manage_screen: inputs.ismanageScreen.value,
                bankData: {
                    nameOnAccount: inputs.accountName.value.substring(0, 22),
                    accountNumber: inputs.accountNumber.value,
                    routingNumber: inputs.routingNumber.value,
                    accountType: inputs.accountType.value,
                    tokenBox: tokenBoxValsAch,
                    pmid: inputs.pmid.value,
                    default_card_method: checkdefault,
                },
            };
        } else {
            if (!this._validateFormInputs('#addCardDetails')) return;
            const tokenBoxValsCredit = document.querySelector('.token_box_credit_vals:checked') ? 'true' : 'false';
            return {
                acquirer_id: acquirerId,
                provider_id: acquirerId,
                update_pm_id: updatePmId,
                cardData: {
                    cardNumber: inputs.card.value.replace(/ /g, ''),
                    name: inputs.name.value,
                    street: inputs.street.value,
                    zip: inputs.zip.value,
                    expiry: inputs.expiry.value,
                    tokenBox: 'true',
                    cardCode: inputs.code.value,
                    pmid: '',
                    default_card_method: checkdefault,
                },
            };
        }
    },

    async _updateEbizAccount(ev) {
        document.getElementById('new_account_tab_id').value = "update_account";
        ev.stopPropagation();
        ev.preventDefault();
        $('input[data-provider="_updateEbizAccountebizcharge"][data-payment-option-type="acquirer"]').click();
        document.querySelectorAll('#ebiz_acquirer_select_auto').forEach((element) => {
            if (element.getAttribute("data-payment-option-name") === 'EBizCharge') {
                element.checked = true;
            }
        });
        $('.update_ebiz_account').prop('disabled', true).css('color', '#bebebe');
        $('.delete_bank_acc').prop('disabled', true).css('color', '#bebebe');
        const pmId = parseInt(ev.currentTarget.value);
        this.currently_updating = ev.target.parentElement;
        await this._getEbizToken(pmId);
    },

    async _updateEbizCard(ev) {
        document.getElementById('new_account_tab_id').value = "update_card";
        ev.stopPropagation();
        ev.preventDefault();
        $('input[data-provider="ebizcharge"][data-payment-option-type="acquirer"]').click();
        document.querySelectorAll('#ebiz_acquirer_select_auto').forEach((element) => {
            if (element.getAttribute("data-payment-option-name") === 'EBizCharge') {
                element.checked = true;
            }
        });
        $('.update_ebiz_card').prop('disabled', true).css('color', '#bebebe').parent().css('cursor', 'default');
        $('.delete_cred_card').prop('disabled', true).css('color', '#bebebe');
        const pmId = parseInt(ev.currentTarget.value);
        this.currently_updating = ev.target.parentElement;
        await this._getEbizToken(pmId);
    },

    async _getEbizToken(tokenId) {
        try {
            const result = await rpc('/payment/ebizcharge/manage/token', { pm_id: tokenId });
            this._populateUpdateFields(result, tokenId);
        } catch (error) {
            if (error instanceof RPCError) {
                this._displayErrorDialog(_t("We are not able to retrieve your payment method at the moment."), error.data.message);
                this._enableButton();
            }
        }
    },

    _switchTab(showTabId, hideTabId, showPaneId, hidePaneId) {
        const showTab = document.getElementById(showTabId);
        const hideTab = document.getElementById(hideTabId);
        const showPane = document.getElementById(showPaneId);
        const hidePane = document.getElementById(hidePaneId);
        if (hidePane) hidePane.classList.remove('show', 'active');
        if (showPane) showPane.classList.add('show', 'active');
        if (hideTab) { hideTab.classList.remove('active'); hideTab.setAttribute('aria-selected', 'false'); }
        if (showTab) { showTab.classList.add('active'); showTab.setAttribute('aria-selected', 'true'); }
    },

    _populateUpdateFields(result, pm_id) {
        if (result.token_type === 'credit') {
            this._switchTab('card-tab', 'account-tab', 'addCardDetails', 'addBankAccountDetails');
            this.$el.find("input[name='card_number']").attr('readonly', 1).val(result.card_number);
            this.$el.find("input[name='account_holder_name']").val(result.account_holder_name);
            this.$el.find("input[name='avs_street']").val(result.avs_street);
            this.$el.find("input[name='avs_zip']").val(result.avs_zip);
            this.$el.find("input[name='card_expiration']").val(`${result.card_exp_month} / ${result.card_exp_year.slice(2, 4)}`);
            this.$el.find("input[name='card_code']").val('');
            this.$el.find("input[name='partner_id']").val(result.partner_id[0]);
            this.$el.find("input[name='update_pm_id']").val(pm_id);
            this.$el.find("input[name='default_card_method']").prop("checked", result.is_default).val(result.is_default);
            this.$el.find("input[name='card_type']").val(result.card_type);
        } else {
            this._switchTab('account-tab', 'card-tab', 'addBankAccountDetails', 'addCardDetails');
            this.$el.find("input[name='bank_account_holder_name']").val(result.account_holder_name);
            this.$el.find("select").val(result.account_type);
            this.$el.find("input[name='bank_account_type']").attr('readonly', 1);
            this.$el.find("input[name='account_number']").val(result.account_number).attr('readonly', 1);
            this.$el.find("input[name='routing_number']").val(result.routing).attr('readonly', 1);
            this.$el.find("input[name='update_pm_id']").val(pm_id);
            this.$el.find("input[name='default_account_method']").prop("checked", result.is_default).val(result.is_default);
            this.$el.find("input[name='card_type']").val(result.card_type);
        }
    },

    _getPaymentOptionId(radio) {
        return Number(radio.dataset['paymentOptionId']);
    },
});

export default publicWidget.registry.eBizPaymentForm;
