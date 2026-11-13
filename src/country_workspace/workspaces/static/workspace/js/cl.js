$(function () {
    $("#result_list tbody tr .field").on("click", function () {
        var url = $(this).parent().find("th a").attr("href");
        location.href = url;
    })

    /* HOPE's Apply: one request with the search term and every edited text filter, not only the search form. */
    var fieldValue = function (field) {
        return field.type === "checkbox" ? String(field.checked) : field.value;
    };
    var originalValue = function (field) {
        return field.type === "checkbox" ? String(field.dataset.original === "true") : field.dataset.original || "";
    };
    var applyFilters = function () {
        var current = new URLSearchParams(location.search);
        var params = new URLSearchParams(location.search);
        var search = document.getElementById("searchbar");
        if (search) {
            search.value ? params.set(search.name, search.value) : params.delete(search.name);
        }
        params.delete("p");
        document.querySelectorAll("#changelist-filter ul[data-qs]").forEach(function (filter) {
            var fields = Array.from(filter.querySelectorAll("input, select, textarea"));
            if (!fields.some(function (f) { return fieldValue(f) !== originalValue(f); })) {
                return;
            }
            // data-qs is the current query without this filter, so the difference is what the filter owns.
            var others = new URLSearchParams(filter.dataset.qs);
            Array.from(current.keys()).forEach(function (key) {
                if (!others.has(key)) params.delete(key);
            });
            var main = filter.querySelector("input[name=key]") || filter.querySelector("textarea, input[type=text]");
            if (!main || !main.value) {
                return;
            }
            fields.forEach(function (f) {
                var lookup = f.dataset.lk || (f.type === "checkbox" ? filter.dataset.lkNegated : filter.dataset.lk);
                if (lookup) params.set(lookup, fieldValue(f));
            });
        });
        location.search = params.toString();
    };
    $("#apply-filters").on("click", applyFilters);
    $("#changelist-search").on("submit", function (e) {
        e.preventDefault();
        applyFilters();
    });
})
