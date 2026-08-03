/** @odoo-module **/
import { patch } from '@web/core/utils/patch';
import { patchDynamicContent } from '@web/public/utils';
import { _t } from "@web/core/l10n/translation";
import { rpc, RPCError } from "@web/core/network/rpc";
import { PaymentForm } from "@payment/interactions/payment_form";

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


patch(PaymentForm.prototype, {
    setup() {
        super.setup();
        this._surchargeTimer = null;
        this.registerCleanup(() => clearTimeout(this._surchargeTimer));
        this.onChangeCalcSurcharge = this.onChangeCalcSurcharge.bind(this);
        this.onParentTabChange = this.onParentTabChange.bind(this);
        this.onChangeNewAccountValue = this.onChangeNewAccountValue.bind(this);
        this.onChangeCardValue = this.onChangeCardValue.bind(this);
        this.onClickCreditTab = this.onClickCreditTab.bind(this);
        this.onClickAccountTab = this.onClickAccountTab.bind(this);

        patchDynamicContent(this.dynamicContent, {
            '.surcharge_calc': { 't-on-change': this.onChangeCalcSurcharge },
            'a.o_payment_provider_select_cc': { 't-on-click': this.onChangeCalcSurcharge },
            'a.parent-tab': { 't-on-click': this.onParentTabChange },
            '[name="new-account-tab"]': { 't-on-click': this.onChangeNewAccountValue },
            '#new-card-tab': { 't-on-click': this.onChangeCardValue },
            '#credit-tab': { 't-on-click': this.onClickCreditTab },
            '#account-tab': { 't-on-click': this.onClickAccountTab },
        });
    },

    async onChangeCardValue(ev) {
        document.querySelectorAll("input[name=o_payment_radio]").forEach(function (element) {
            const dataValue = element.getAttribute("data-provider-code");
            const paymentMethod = element.getAttribute("data-payment-option-type");
            if (dataValue == 'ebizcharge' && paymentMethod == 'payment_method') {
                element.checked = true;
            }
        });
        initializeSavedCardTab();
    },

    async onParentTabChange(ev) {
        $('#new_account_tab_id_val').val('');
        if ($(ev.currentTarget).attr('aria-controls') === "account"){
            if ($('#save-account-tab').hasClass('active')) {
                $('#new_account_tab_id_val').val('save_account_val');
            }
            else if ($('#new-account-tab').hasClass('active')) {
                $('#new_account_tab_id_val').val('new_account_val');
            }
        }
        else if ($(ev.currentTarget).attr('aria-controls') === "credit") {
            if ($('#save-card-tab').hasClass('active')) {
                $('#new_account_tab_id_val').val('save_card_val');
            }
            else if ($('#new-card-tab').hasClass('active')) {
                $('#new_account_tab_id_val').val('new_card_val');
            }
        }
    },

    onChangeNewAccountValue(ev) {
        if (document.getElementById("new_account_tab_id_val")) {
            document.querySelectorAll("input[name=o_payment_radio]").forEach(function (element) {
                const dataValue = element.getAttribute("data-provider-code");
                const paymentMethod = element.getAttribute("data-payment-option-type");
                if (dataValue == 'ebizcharge' && paymentMethod == 'payment_method') {
                    element.checked = true;
                }
            });
            document.getElementById("new_account_tab_id_val").value = "new_account_val";
        }
    },

    validateValuesBeforeSurchargeCheck(pm_vals) {
        const ccNumber = document.getElementById('cc_number').value;
        const avsZip = document.getElementById('avs_zip').value;
        const newCardTab = $('#new-card-tab').hasClass('active');
        if (pm_vals != '0' || (ccNumber != '' && avsZip != '' && newCardTab)) {
            return true;
        }
        return false;
    },

    onClickCreditTab(ev) {
        initializeNewBankAccountTab();
        initializeSavedBankAccountTab();
        this.initializeSurchargeAmount();
    },

    onClickAccountTab(ev) {
        initializeNewCardTab();
        initializeSavedCardTab();
        this.initializeSurchargeAmount();
    },

    initializeSurchargeAmount() {
        const amountTotal = $('#total_order_amt_ebiz').val();
        $('#sur_amt_ebiz').text(parseFloat('0').toFixed(2));
        $('#sur_amt_ebiz_total').text(parseFloat(amountTotal).toFixed(2));
    },

    onChangeCalcSurcharge(ev) {
        this.initializeSurchargeAmount();
        const checkedRadio = this.el.querySelector('input[name="o_payment_radio"]:checked');
        const allow_surcharge = document.getElementById('allow_pay_surcharge')?.value || 'false';
        let pm_vals = '0';
        if (checkedRadio && $('#save-card-tab').hasClass('active')) {
            pm_vals = checkedRadio.value.split('-')[0];
            if (pm_vals === 'on') pm_vals = '0';
        }
        if (allow_surcharge !== 'True' || !this.validateValuesBeforeSurchargeCheck(pm_vals)) return;
        clearTimeout(this._surchargeTimer);
        this._surchargeTimer = setTimeout(async () => {
            const spinner = document.getElementById('surcharge_loading');
            if (spinner) spinner.classList.remove('d-none');
            this._disableButton(true);
            try {
                const params = {
                    'pm_id': pm_vals,
                    'amount': document.getElementById('total_order_amt_ebiz').value,
                    'cc_number': document.getElementById('cc_number').value,
                    'avs_zip': document.getElementById('avs_zip').value,
                };
                const result = await rpc('/surcharge/check', { kwargs: params });
                const amountTotal = parseFloat(document.getElementById('total_order_amt_ebiz').value);
                document.getElementById('sur_amt_ebiz').textContent = result.amount.toFixed(2);
                document.getElementById('sur_amt_ebiz_total').textContent = (amountTotal + result.amount).toFixed(2);
            } catch {
                this.initializeSurchargeAmount();
            } finally {
                if (spinner) spinner.classList.add('d-none');
                this._enableButton();
            }
        }, 300);
    },

    _getErrorMessage(element) {
        const $group = $(element).closest('div.form-group');
        for (const [cls, msg] of Object.entries(FIELD_ERROR_MESSAGES)) {
            if ($group.hasClass(cls)) return msg;
        }
        return "The value is invalid.";
    },

    async selectPaymentOption(ev) {
        const checkedRadio = this.el.querySelector('input[name="o_payment_radio"]:checked');
        const providerCode = this.paymentContext.providerCode = this._getProviderCode(checkedRadio);
        if (providerCode !== 'ebizcharge') {
            return super.selectPaymentOption(...arguments);
        }
        this.onChangeCalcSurcharge(ev);
        this._showHideSecurityInput(checkedRadio);
        await super.selectPaymentOption(...arguments);
    },

    _showHideSecurityInput(checkedRadio) {
        const pm_id = parseInt(checkedRadio.value.split('-')[0]);
        const token_type = checkedRadio.value.split('-')[1];
        if (token_type === 'ebizchargeCard') {
            document.getElementById(pm_id).style.display = 'block';
            document.getElementById('security-code-heading').style.display = 'table-cell';
            document.getElementsByName("o_payment_radio").forEach(function (element) {
                if (!element.checked && element.value.includes('ebizchargeCard')) {
                    document.getElementById(parseInt(element.value.split('-')[0])).style.display = 'none';
                }
            });
        } else {
            if (document.getElementById('security-code-heading')) {
                document.getElementById('security-code-heading').style.display = 'none';
                document.getElementsByName("o_payment_radio").forEach(function (element) {
                    if (!element.checked && element.value.includes('ebizchargeCard')) {
                        document.getElementById(parseInt(element.value.split('-')[0])).style.display = 'none';
                    }
                });
            }
        }
    },

    _getAcquirerTypeFromCheckbox(element) {
        return element?.[0]?.id;
    },

    getFormData($form) {
        return Object.fromEntries($form.serializeArray().map(({ name, value }) => [name, value]));
    },

    _getInlineFormInputsEBiz(acquirerId) {
        let acquirerType = '';
        if (document.getElementById('new_account_tab_id_val')) {
            acquirerType = document.getElementById('new_account_tab_id_val').value;
        }
        if (acquirerType === 'new_account_val') {
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
        } else {
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
        }
    },

    async _getPaymentDetailsEBiz(acquirerId) {
        const inputs = this._getInlineFormInputsEBiz(acquirerId);
        let acquirerType = '';
        if (document.getElementById('new_account_tab_id_val')) {
            acquirerType = document.getElementById('new_account_tab_id_val').value;
        }
        const checkdefault = document.querySelector('.default_check:checked') ? 'true' : 'false';
        if (acquirerType === 'new_account_val') {
            const tokenBoxValsAch = (inputs.tokenAccBox?.checked || inputs.tokenAccBox?.value === 'True')
                ? 'true' : 'false';
            return {
                acquirer_id: acquirerId,
                provider_id: acquirerId,
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
            const tokenBoxValsCredit = document.querySelector('.token_box_credit_vals:checked') ? 'true' : 'false';
            return {
                acquirer_id: acquirerId,
                provider_id: acquirerId,
                cardData: {
                    cardNumber: inputs.card.value.replace(/ /g, ''),
                    name: inputs.name.value,
                    street: inputs.street.value,
                    zip: inputs.zip.value,
                    expiry: inputs.expiry.value,
                    tokenBox: tokenBoxValsCredit,
                    cardCode: inputs.code.value,
                    pmid: '',
                    default_card_method: checkdefault,
                },
            };
        }
    },

    async _prepareInlineForm(providerId, providerCode, paymentOptionId, paymentMethodCode, flow) {
        if (providerCode !== 'ebizcharge') {
            return super._prepareInlineForm(...arguments);
        }
        if (flow === 'token') {
            return Promise.resolve();
        }
        this._setPaymentFlow('direct');
    },

    _prepareTransactionRouteParamsEbiz(tokenEbiz) {
        const transactionRouteParams = {
            'provider_id': this.paymentContext.providerId,
            'payment_method_id': this.paymentContext.paymentMethodId ?? null,
            'token_id': this.paymentContext.tokenId ?? null,
            'amount': this.paymentContext['amount'] !== undefined ?
                parseFloat(this.paymentContext['amount']) : null,
            'flow': this.paymentContext['flow'],
            'tokenization_requested': this.paymentContext['tokenizationRequested'],
            'landing_route': this.paymentContext['landingRoute'],
            'is_validation': this.paymentContext['mode'] === 'validation',
            'token_ebiz': tokenEbiz,
            'access_token': this.paymentContext['accessToken'],
            'csrf_token': odoo.csrf_token,
        };
        if (this.paymentContext['transactionRoute'] === '/payment/transaction') {
            Object.assign(transactionRouteParams, {
                'currency_id': this.paymentContext['currencyId'] ?
                    parseInt(this.paymentContext['currencyId']) : null,
                'partner_id': parseInt(this.paymentContext['partnerId']),
                'reference_prefix': this.paymentContext['referencePrefix']?.toString(),
            });
        }
        if (this.paymentContext.paymentReference) {
            transactionRouteParams.payment_reference = this.paymentContext.paymentReference;
        }
        return transactionRouteParams;
    },

    async submitForm(ev) {
        ev.stopPropagation();
        ev.preventDefault();
        const checkedRadio = this.el.querySelector('input[name="o_payment_radio"]:checked');
        const providerCode = this._getProviderCode(checkedRadio);

        if (providerCode !== 'ebizcharge') {
            await super.submitForm(...arguments);
            return;
        }
        this._disableButton(true);

        const is_saved_card = checkedRadio.value.includes('ebizchargeCard');
        const is_saved_bank = checkedRadio.value.includes('ebizchargeAccount');

        if (providerCode === 'ebizcharge' && !is_saved_card && !is_saved_bank) {
            const tab = $('.nav-link.active');
            const acquirerType = this._getAcquirerTypeFromCheckbox(tab);
            if (acquirerType !== 'account-tab' && acquirerType !== 'credit-tab') {
                this._enableButton();
                this._displayErrorDialog(
                    _t("Payment processing failed"),
                    _t("Configuration required. Please add a valid website to the EBizCharge Merchant Account or select a merchant account on the customer profile.")
                );
                return;
            }
            if (!this._validateNewCardInputs(acquirerType)) {
                this._enableButton();
                return;
            }

            const tokenEbiz = await this._getPaymentDetailsEBiz(this._getProviderId(checkedRadio));
            if (ev.currentTarget.form) {
                const partnerId = ev.currentTarget.form.dataset.partnerId;
                if (partnerId) {
                    tokenEbiz.partner_id = parseInt(partnerId);
                }
            }

            const isSave = tokenEbiz.cardData?.tokenBox === 'true' || tokenEbiz.bankData?.tokenBox === 'true';

            this.paymentContext.providerId = this._getProviderId(checkedRadio);
            const paymentOptionId = this.paymentContext.paymentOptionId = this._getPaymentOptionId(checkedRadio);
            const inlineForm = this._getInlineForm(checkedRadio);
            this.paymentContext.tokenizationRequested = inlineForm?.querySelector(
                '[name="o_payment_tokenize_checkbox"]'
            )?.checked ?? this.paymentContext['mode'] === 'validation';
            this.paymentContext.paymentMethodId = paymentOptionId;
            const newCardProviderCode = this.paymentContext.providerCode = this._getProviderCode(checkedRadio);
            const pmCode = this.paymentContext.paymentMethodCode = this._getPaymentMethodCode(checkedRadio);

            const handleTransactionError = (error) => {
                if (error instanceof RPCError) {
                    this._enableButton();
                    this._displayErrorDialog(_t("Payment processing failed"), error.data.message);
                } else {
                    return Promise.reject(error);
                }
            };

            if (isSave) {
                rpc('/payment/ebizcharge/s2s/create_json_3ds', { kwargs: tokenEbiz }).then(ebizProcessingValues => {
                    if (!ebizProcessingValues || !ebizProcessingValues.result) {
                        this._enableButton();
                        this._displayErrorDialog(
                            _t("Payment processing failed"),
                            ebizProcessingValues?.error || _t("An unexpected error occurred.")
                        );
                        return;
                    }
                    this.paymentContext.tokenId = ebizProcessingValues.id;
                    this.paymentContext.flow = 'token';
                    rpc(
                        this.paymentContext['transactionRoute'],
                        this._prepareTransactionRouteParamsEbiz(null),
                    ).then(processingValues => {
                        this._processTokenFlow(newCardProviderCode, paymentOptionId, pmCode, processingValues);
                    }).catch(handleTransactionError);
                }).catch(handleTransactionError);
            } else {
                this.paymentContext.tokenId = null;
                this.paymentContext.flow = 'direct';
                rpc(
                    this.paymentContext['transactionRoute'],
                    this._prepareTransactionRouteParamsEbiz(tokenEbiz),
                ).then(processingValues => {
                    this._processTokenFlow(newCardProviderCode, paymentOptionId, pmCode, processingValues);
                }).catch(handleTransactionError);
            }
        }

        if (checkedRadio.value.includes('ebizchargeCard') && is_saved_card == true) {
            const form = this.el;
            let isValue = false;

            for (let i = 1; i < form.elements.length; i++) {
                if (checkedRadio.value.split('-')[0] === form[i].id) {
                    if (form[i].name === 'security-code') {
                        if (form[i].value != "" && form[i].value.length >= 3) {
                            isValue = true;
                        }
                    }
                }
            }
            if (isValue === false) {
                this._enableButton();
                this._displayErrorDialog(
                    _t("Payment processing failed"),
                    _t("Please enter valid security code while paying with saved cards.")
                );
                return;
            } else {
                return await super.submitForm(...arguments);
            }
        } else if (checkedRadio.value.includes('ebizchargeAccount') && is_saved_bank == true) {
            return await super.submitForm(...arguments);
        }
    },

    _validateNewCardInputs(acquirerType) {
        const selector = acquirerType === 'account-tab' ? '#addBankAccountDetails' : '#addCardDetails';
        const validateInputsForm = $('input, select', selector);
        let hasError = false;
        const self = this;
        validateInputsForm.toArray().forEach(function (element) {
            if ($(element).attr('type') === 'hidden') return true;

            const $group = $(element).closest('div.form-group');
            $group.removeClass('o_has_error').find('.form-control, .custom-select').removeClass('is-invalid');
            $(element).siblings('.o_invalid_field').remove();
            $(element).trigger("focusout");

            let message = null;
            if ((element.dataset.isRequired && element.value.length === 0) || $group.hasClass('o_has_error')) {
                message = self._getErrorMessage(element);
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
        });
        return !hasError;
    },

});

function setCardNumberToBlank() {
    $('#cc_number').val('');
    $('#cc_number').parent('.form-group').removeClass('o_has_success').find('.form-control, .custom-select').removeClass('is-valid');
    $('#cc_number').parent('.form-group').removeClass('o_has_error').find('.form-control, .custom-select').removeClass('is-invalid');
    $('#cc_number').siblings('.o_invalid_field').remove();
}

function setCardHolderNameToBlank() {
    $('#cc_holder_name').val('');
    $('#cc_holder_name').parent('.form-group').removeClass('o_has_error').find('.form-control, .custom-select').removeClass('is-invalid');
    $('#cc_holder_name').siblings('.o_invalid_field').remove();
}

function setAvsStreetToBlank() {
    $('#avs_street').val('');
    $('#avs_street').parent('.form-group').removeClass('o_has_error').find('.form-control, .custom-select').removeClass('is-invalid');
    $('#avs_street').siblings('.o_invalid_field').remove();
}

function setAvsZipToBlank() {
    $('#avs_zip').val('');
    $('#avs_zip').parent('.form-group').removeClass('o_has_error').find('.form-control, .custom-select').removeClass('is-invalid');
    $('#avs_zip').parent('.form-group').removeClass('o_has_success').find('.form-control, .custom-select').removeClass('is-valid');
}

function setCCExpiryToBlank() {
    $('#cc_expiry').val('');
    $('#cc_expiry').parent('.form-group').removeClass('o_has_error').find('.form-control, .custom-select').removeClass('is-invalid');
    $('#cc_expiry').parent('.form-group').removeClass('o_has_success').find('.form-control, .custom-select').removeClass('is-valid');
}

function setCCCVCToBlank() {
    $('#cc_cvc').val('');
    $('#cc_cvc').parent('.form-group').removeClass('o_has_success').find('.form-control, .custom-select').removeClass('is-valid');
    $('#cc_cvc').parent('.form-group').removeClass('o_has_error').find('.form-control, .custom-select').removeClass('is-invalid');
    $('#cc_cvc').siblings('.o_invalid_field').remove();
}

function initializeNewCardTab() {
    setCardNumberToBlank();
    setCardHolderNameToBlank();
    setAvsStreetToBlank();
    setAvsZipToBlank();
    setCCExpiryToBlank();
    setCCCVCToBlank();

    $('#token_save_box_credit').prop('checked', false);
    $('#default_card_method').prop('checked', false);
}

function initializeSavedCardTab() {
    const checkedRadio = $('input[name="o_payment_radio"]');
    if (checkedRadio && $('#save-card-tab').hasClass('active')) {
        checkedRadio.prop('checked', false).change();
    }
    $('input[name="security-code"]').removeClass('is-valid').parent('.form-group').removeClass('o_has_success');
    $('input[name="security-code"]').removeClass('is-invalid').parent('.form-group').removeClass('o_has_error');
    $('input[name="security-code"]').siblings('.o_invalid_field').remove();
    $('input[name="security-code"]').val('');
}

function setAccountHolderNameToBlank() {
    $('#bank_account_holder_name').val('');
    $('#bank_account_holder_name').parent('.form-group').removeClass('o_has_error').find('.form-control, .custom-select').removeClass('is-invalid');
    $('#bank_account_holder_name').siblings('.o_invalid_field').remove();
}

function setAccountNumberToBlank() {
    $('#account_number').val('');
    $('#account_number').parent('.form-group').removeClass('o_has_success').find('.form-control, .custom-select').removeClass('is-valid');
    $('#account_number').parent('.form-group').removeClass('o_has_error').find('.form-control, .custom-select').removeClass('is-invalid');
    $('#account_number').siblings('.o_invalid_field').remove();
}

function setRoutingNumberToBlank() {
    $('#routing_number').val('');
    $('#routing_number').parent('.form-group').removeClass('o_has_success').find('.form-control, .custom-select').removeClass('is-valid');
    $('#routing_number').parent('.form-group').removeClass('o_has_error').find('.form-control, .custom-select').removeClass('is-invalid');
    $('#routing_number').siblings('.o_invalid_field').remove();
}

function initializeNewBankAccountTab() {
    setAccountHolderNameToBlank();
    setAccountNumberToBlank();
    setRoutingNumberToBlank();

    $('#bank_account_type').val('Checking');
    $('#token_save_box_acc').prop('checked', false);
    $('#default_account_method').prop('checked', false);
}

function initializeSavedBankAccountTab() {
    const checkedRadio = $('input[name="o_payment_radio"]');
    if (checkedRadio && $('#save-account-tab').hasClass('active')) {
        checkedRadio.prop('checked', false).change();
    }
}
