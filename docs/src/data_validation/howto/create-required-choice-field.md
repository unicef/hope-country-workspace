This guide shows how to create a required choice field and use it in a [DataChecker configuration](../datachecker_configuration.md).

The example creates the `sex` [Flex Field](../datachecker_configuration.md#flex-field). In HOPE Core, `sex` is expected in the beneficiary data structure, so the final DataChecker field must include `"required": true`.

## 1. Create a Field Definition

Open **Field Definitions**, click **Add Field Definition**, and create a new record:

- **Name**: `HOPE Ind Sex`;
- **Field type**: `ChoiceFieldWithEmptyDisplay`;
- **Description**: `Required sex field expected by HOPE Core.`

Save the record.

Open the created [Field Definition](../datachecker_configuration.md#field-definition) and click **Configure**.

Set the field attributes:

```json
{
  "label": "Sex",
  "required": true,
  "choices": [
    ["MALE", "Male"],
    ["FEMALE", "Female"],
    ["OTHER", "Other"],
    ["NOT_COLLECTED", "Not collected"],
    ["NOT_ANSWERED", "Not answered"]
  ]
}
```

Save the configuration.

Use **Test** to check that the field requires a value and accepts only one of the configured choices.

## 2. Create or update a Fieldset

Open **Fieldsets** and select the Fieldset that should contain the `sex` field.

For example, use an existing individual core Fieldset if `sex` belongs to the individual beneficiary structure.

## 3. Create a Flex Field

Open **Flex Fields**, click **Add Flex Field**, and create a new record:

* **Name**: `sex`;
* **Definition**: `HOPE Ind Sex`;
* **Fieldset**: `HOPE Individual core base`.

Leave **Master** empty.

If `"required": true` is already configured on the Field Definition, leave **Overrides** empty.

If the same Field Definition is reused in another context where the field is not always required, set **Overrides › Attrs** on this Flex Field instead:

```json
{
  "required": true
}
```

Save the record.

The `sex` name must match the field name expected by HOPE Core.

## 4. Add the Fieldset to a DataChecker

Open the required [DataChecker](../datachecker_configuration.md#datachecker) and make sure it includes the Fieldset with the `sex` field.

Save the record.

## 5. Check the final configuration

Open the DataChecker and use **Inspect**.

Check that the generated `sex` field contains:

```json
{
  "required": true
}
```

Use **Test** or **Validate** to confirm that records without `sex` fail validation.
