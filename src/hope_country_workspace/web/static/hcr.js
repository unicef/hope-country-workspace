(function ($) {

    $(function () {
        function updateQueryStringParameter(uri, key, value) {
            var re = new RegExp("([?&])" + key + "=.*?(&|$)", "i");
            var separator = uri.indexOf('?') !== -1 ? "&" : "?";
            if (uri.match(re)) {
                return uri.replace(re, '$1' + key + "=" + value + '$2');
            } else {
                return uri + separator + key + "=" + value;
            }
        }

        function getQueryVariable(variable) {
            var query = window.location.search.substring(1);
            var vars = query.split('&');
            for (var i = 0; i < vars.length; i++) {
                var pair = vars[i].split('=');
                if (decodeURIComponent(pair[0]) == variable) {
                    return decodeURIComponent(pair[1]);
                }
            }
            console.log('Query variable %s not found', variable);
        }

        $("#close-sidebar").on("click", function () {
            $("#sidebar").addClass("w-16").removeClass("w-52");
            $("#open-sidebar").removeClass("hidden");
            $(".display-open").hide()
        })
        $("#open-sidebar").on("click", function () {
            $("#sidebar").addClass("w-52").removeClass("w-16");
            $("#logo").addClass("hidden");
            $("#open-sidebar").addClass("hidden");
            $(".display-open").show()
        })
        $('#select-tenant select').on('change', function () {
            $('#select-tenant').submit();
        })
        var currentPage = $('meta[name=view]').attr("content");
        if (currentPage) {
            $(`.${currentPage}`).addClass("selected");
        }

        $(".tag-filter").on("click", function (e) {
            e.preventDefault();
            // const url = new URL(location.href);
            // const params = new URLSearchParams(url.search);
            // console.log(1111, params);
            if (e.shiftKey) {
                let current = getQueryVariable("tag");

                let newUrl = updateQueryStringParameter(location.href, "tag", $(this).data("tag"))
            } else {
                let newUrl = updateQueryStringParameter(location.href, "tag", $(this).data("tag"))
            }

            console.log(111111, newUrl);
        });


        function delay(callback, ms) {
            var timer = 0;
            return function () {
                var context = this, args = arguments;
                clearTimeout(timer);
                timer = setTimeout(function () {
                    callback.apply(context, args);
                }, ms || 0);
            };
        }

        $("#filterInput").on("keyup", delay(function () {
            let filter = this.value.toUpperCase();
            $("table.searchable tr").each(function (i, el) {
                let txt = $(el).find("td,caption").text();
                if (txt.toUpperCase().indexOf(filter) > -1) {
                    $(el).closest(".section").show();
                    $(el).show();
                } else {
                    $(el).hide();
                }
                $("table.section").each(function (i, t) {
                    if ($(t).find("tr:visible").length === 0) {
                        $(t).hide();
                    }
                });
            });
        }, 300)).trigger("keyup").focus();

        $(".messages .message .close").on("click", function () {
            $(this).parent(".message").hide();
        })

        function close(t) {
            return function () {
                $(`.timeout-${t}`).hide()
            };
        }

        setTimeout(close(5), 5000);
    })
})(jQuery || django.jQuery)
