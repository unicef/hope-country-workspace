(function($) {
    'use strict';

    $(function() {

        $('#content-main').on('click', '.reset-link', function(e) {
            e.preventDefault();

            const field_selector = this.dataset.fieldId.replace(/ /g, "\\ ")
            const field = $('#' + field_selector);
            const fieldType = this.dataset.fieldType;

            if (fieldType === 'checkbox') {
                field.prop('checked', this.dataset.default === 'true');
            } else if (fieldType === 'date') {
                const defaultDate = new Date(this.dataset.default * 1000);
                $('#' + this.dataset.fieldId).val(defaultDate.strftime(get_format('DATE_INPUT_FORMATS')[0]));
            } else if (fieldType === 'datetime') {
                const defaultDate = new Date(this.dataset.default * 1000);
                $('#' + this.dataset.fieldId + '_0').val(defaultDate.strftime(get_format('DATE_INPUT_FORMATS')[0]));
                $('#' + this.dataset.fieldId + '_1').val(defaultDate.strftime(get_format('TIME_INPUT_FORMATS')[0]));
            } else {
                field.val(this.dataset.default);
            }
        });
    });
})(django.jQuery);
