(function ($) {
    $(function () {

        let $short = $("#sql-short");
        let $full = $("#sql-full");

        $short.on("click", function () {
            $short.hide()
            $full.show()
        })
        $full.on("click", function () {
            $full.hide()
            $short.show()
        })
    });
})(jQuery || django.jQuery);
