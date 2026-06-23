This guide shows how to create a custom multiple choice field and use it in a [DataChecker configuration](../datachecker_configuration.md).

The example creates a `support_needs` [Flex Field](../datachecker_configuration.md#flex-field) with three possible values:

* `food`;
* `cash`;
* `shelter`.

The field will allow selecting more than one value.

## 1. Create a Field Definition

Open **Field Definitions**, click **Add Field Definition**, and create a new record:

* **Name**: `Support needs choices`;
* **Field type**: `CustomMultipleChoiceField`;
* **Description**: `Multiple choice field for household support needs.`

Save the record.

Open the created [Field Definition](../datachecker_configuration.md#field-definition) and click **Configure**.

Set the field attributes:

```json
{
  "label": "Support needs",
  "required": false,
  "help_text": "Select one or more support needs.",
  "choices": [
    ["food", "Food assistance"],
    ["cash", "Cash assistance"],
    ["shelter", "Shelter support"]
  ]
}
```

Save the configuration.

Use **Test** to check that the field accepts one or more selected values.

## 2. Create a Fieldset

Open **Fieldsets**, click **Add Fieldset**, and create a new record:

* **Name**: `Household support needs`;
* **Description**: `Fields related to household support needs.`

Leave **Extends**, **Content type**, **Group**, and **Validation** empty.

Save the record.

This [Fieldset](../datachecker_configuration.md#fieldset) will group the fields related to household support needs.

## 3. Create a Flex Field

Open **Flex Fields**, click **Add Flex Field**, and create a new record:

* **Name**: `support_needs`;
* **Definition**: `Support needs choices`;
* **Fieldset**: `Household support needs`.

Leave **Master** and **Overrides** empty.

Save the record.

The `support_needs` name is used in imports, validation, and beneficiary data.

## 4. Create a DataChecker

Open **DataCheckers**, click **Add DataChecker**, and create a new record:

* **Name**: `Household support needs checker`;
* **Description**: `Validation configuration for household support needs.`

In **Data Checker Fieldsets**, add the new `Household support needs` Fieldset together with the existing Fieldsets required by the beneficiary structure.

For example, add:

* `HOPE Household core`;
* `HOPE Admin Areas`;
* `Household support needs`.

For the `Household support needs` Fieldset, use:

* **Prefix**: empty;
* **Order**: `3`;
* **Override group default value**: unchecked.

Save the record.

The [DataChecker](../datachecker_configuration.md#datachecker) is the final validation configuration that can be assigned to a Program.

## 5. Test the configuration

Open the created DataChecker and use:

* **Inspect** to check that `support_needs` is included in the generated field structure;
* **Test** to validate the field manually;
* **Create XLS importer** to generate an import template;
* **Validate** to test a sample import file.

Example valid values for import:

```text
food,cash
```

or:

```text
food cash
```

The value will be treated as a list of selected choices.
