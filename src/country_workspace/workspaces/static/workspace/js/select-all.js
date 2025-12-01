$(function () {
    $("#select-all").change(function () {
        $(this)
            .closest("form")
            .find("input:checkbox[name='fields']")
            .prop('checked', this.checked);
    })
})
