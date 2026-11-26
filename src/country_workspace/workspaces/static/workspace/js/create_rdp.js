"use strict";

for (const checkbox of document.querySelectorAll('#create-rdp-form input[name="rdp_operations"]')) {
    const fieldset = checkbox.closest("section").querySelector("fieldset");
    const update = () => {
        fieldset.disabled = !checkbox.checked;
    };
    checkbox.addEventListener("change", update);
    update();
}
