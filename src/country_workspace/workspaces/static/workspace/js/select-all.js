$(function () {
    $("#select-all").change(function () {
        $(this).parent("form").children("input:checkbox").not(this).prop('checked', this.checked);
    })
})
