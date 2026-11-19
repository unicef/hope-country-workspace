$(function () {
    $("#tabs ul li button").on("click", function (){
        $("#tabs ul li button.selected").removeClass("selected");
        $(this).addClass("selected");
        $(this).data("selected");
        $("#tab-content div.content").addClass("hidden").hide();
        $($(this).data("tabs-target")).removeClass("hidden").show();
        $("input[name=_selected_tab]").val($(this).data("input-value"));
    });

    // Selects backed by an external API are rendered disabled; fill them without blocking the page.
    $("select[data-lazy-choices]").each(function () {
        var $select = $(this);
        var $submit = $select.closest("form").find("input[type=submit]");
        var $help = $select.siblings(".helptext, .help").first();
        var params = new URLSearchParams(window.location.search);
        params.set("_import_choices", $select.data("lazy-choices"));
        $submit.prop("disabled", true);
        $.getJSON(window.location.pathname + "?" + params.toString())
            .done(function (data) {
                $select.empty();
                $.each(data.choices, function (_, choice) {
                    $select.append($("<option>").val(choice[0]).text(choice[1]));
                });
                $select.prop("disabled", false);
                $submit.prop("disabled", false);
            })
            .fail(function (xhr) {
                var message = (xhr.responseJSON && xhr.responseJSON.error) || "Could not load the list. Please try again later.";
                $select.empty().append($("<option>").val("").text("—"));
                $select.after($("<p class='errornote'>").text(message));
            });
    });
})
