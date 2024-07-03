(function ($) {
    $(function () {
        var $panel = $("#celery-info-panel");
        $("#celery-info").on("click", function () {
            $panel.toggleClass("hidden");
        })
    });
})(jQuery);
