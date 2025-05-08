$(function () {
    $("#select-all").change(function () {
        $(this)
            .closest("form")
            .find("input:checkbox")
            .not(this)
            .prop('checked', this.checked);
    })
})
