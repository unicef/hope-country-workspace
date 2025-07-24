# System Context Diagram

This diagram provides a high-level view of the *Country Workspace* system in its broader environment.
It highlights key external actors and systems interacting with Country Workspace:

- `Program Administrator`: configures the system and synchronizes reference data
- `Data Processor`: processes beneficiary data through the workflow
- External systems providing data: `Aurora API`, `Kobo API`, `Excel Files`
- External target system: `HOPE Core`

Country Workspace synchronizes reference data from HOPE Core, ingests data from various external sources, and exports processed data back to HOPE Core.
Relationships are styled to reflect the origin system for clarity.


```mermaid

C4Context

    Person(admin, "Program Administrator", "Configures system and synchronizes reference data")
    Person(processor, "Data Processor", "Processes beneficiary data through full workflow")

    System(cw_system, "Country Workspace", "Beneficiary data processing system")

    System_Ext(xlsx_files, "Excel Files", "Spreadsheet data source")
    System_Ext(aurora_api, "Aurora API", "External beneficiary data")
    System_Ext(kobo_api, "Kobo API", "External beneficiary data")
    System_Ext(hope_core, "HOPE Core", "Reference data source and target system")

    Rel(admin, cw_system, "Configures<br>Synchronizes")
    Rel(processor, cw_system, "Processes data")

    Rel(cw_system, hope_core, "Syncs reference data<br>Pushes processed data")
    BiRel(cw_system, xlsx_files, "Import/Export")
    Rel(aurora_api, cw_system, "Provides beneficiary data")
    Rel(kobo_api, cw_system, "Provides beneficiary data")

    UpdateElementStyle(admin, $bgColor="lightsteelblue", $fontColor="black", $borderColor="steelblue")
    UpdateElementStyle(processor, $bgColor="lightsteelblue", $fontColor="black", $borderColor="steelblue")

    UpdateElementStyle(cw_system, $bgColor="lightcyan", $fontColor="black", $borderColor="darkslategray")

    UpdateElementStyle(xlsx_files, $bgColor="lavender", $fontColor="black", $borderColor="slateblue")
    UpdateElementStyle(aurora_api, $bgColor="lavender", $fontColor="black", $borderColor="slateblue")
    UpdateElementStyle(kobo_api, $bgColor="lavender", $fontColor="black", $borderColor="slateblue")
    UpdateElementStyle(hope_core, $bgColor="lightyellow", $fontColor="black", $borderColor="darkgoldenrod")

    UpdateRelStyle(admin, cw_system, $textColor="steelblue", $lineColor="steelblue", $offsetX="-30", $offsetY="0")
    UpdateRelStyle(processor, cw_system, $textColor="steelblue", $lineColor="steelblue", $offsetX="0", $offsetY="0")
    UpdateRelStyle(cw_system, xlsx_files, $textColor="slateblue", $lineColor="slateblue", $offsetX="-40", $offsetY="0")
    UpdateRelStyle(aurora_api, cw_system, $textColor="slateblue", $lineColor="slateblue", $offsetX="-80", $offsetY="0")
    UpdateRelStyle(kobo_api, cw_system, $textColor="slateblue", $lineColor="slateblue", $offsetX="-50", $offsetY="0")
    UpdateRelStyle(cw_system, hope_core, $textColor="darkgoldenrod", $lineColor="darkgoldenrod", $offsetX="-50", $offsetY="90")

    UpdateLayoutConfig($c4ShapeInRow="2", $c4BoundaryInRow="1")


```
