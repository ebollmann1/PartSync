/** @odoo-module **/
import { useInputField } from "@web/views/fields/input_field_hook";
import { Component, useRef, onWillUpdateProps, onPatched } from "@odoo/owl";

export class FieldMaskingBase extends Component {
    static fieldName = "";
    static refName = "";

    setup() {
        super.setup();
        const fieldName = this.constructor.fieldName;

        useInputField({
            getValue: () => this.props.record._initialTextValues[fieldName] || "",
            refName: this.constructor.refName,
        });

        this.inputRef = useRef("input");
        this._maskKey();

        onWillUpdateProps((nextProps) => this._updateKey(nextProps));
        onPatched(() => this._maskKey());
    }

    _maskKey() {
        const fieldName = this.constructor.fieldName;
        const key = this.props.record.data[fieldName] || "";
        if (key) {
            this.props.record._initialTextValues[fieldName] = this._getMaskedKey(key);
        }
    }

    _getMaskedKey(key) {
        const segments = key.match(/.{1,8}/g) || [];
        if (segments.length < 2) return key;
        const [startValue, ...rest] = segments;
        const endValue = rest.pop() || "";
        return `${startValue}_****_***_****_${endValue}`;
    }

    _updateKey(nextProps) {
        const fieldName = this.constructor.fieldName;
        const key = nextProps.record.data[fieldName];
        if (key) {
            nextProps.record._initialTextValues[fieldName] = this._getMaskedKey(key);
        }
    }
}
