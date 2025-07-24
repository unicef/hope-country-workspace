# Component diagram

## Import Processor

This diagram shows the internal component structure of the *Import Processor* container and its interactions with external systems.

**Core Components:**

- `Import Controller`: Orchestrates the import workflow as a Celery task
- `File Reader`: Parses XLSX files from the file system
- `API Fetcher`: Retrieves data from Aurora and Kobo REST APIs
- `Mapping Importer`: Maps external field names to internal schema
- `Validation Component`: Validates data using configurable datacheckers
- `Import Repository`: Persists validated data to the database

**Data Flow:**

1. Web Application triggers import via Import Controller
2. Controller initiates parallel data collection (File Reader for XLSX, API Fetcher for external APIs)
3. Raw data flows through Mapping Importer for schema transformation
4. Validation Component applies datacheckers to mapped data
5. Import Repository persists valid data to Database

**External Dependencies:**

- Excel Files, Aurora API, and Kobo API serve as data sources
- Database stores the processed results

```mermaid

C4Component

    Container(web_app, "Web Application", "Django/Tailwind", "UI for administrators and processors")
    ContainerDb(database, "Database", "PostgreSQL", "Stores imported and validated data")
    System_Ext(aurora_api, "Aurora API", "Provides beneficiary data")
    System_Ext(kobo_api, "Kobo API", "Provides beneficiary data")
    System_Ext(xlsx_files, "Excel Files", "Spreadsheet data source")

    Container_Boundary(import_processor, "Import Processor") {
        Component(import_controller, "Import Controller", "Celery Task", "Handles import workflow orchestration")
        Component(file_reader, "File Reader", "Python", "Parses XLSX files")
        Component(api_fetcher, "API Fetcher", "Python/Requests", "Fetches data from Aurora and Kobo APIs")
        Component(mapping_importer, "Mapping Importer", "Python", "Maps field names from external data to internal schema")
        Component(validation_component, "Validation Component", "Python", "Validates data using datacheckers")
        Component(repository, "Import Repository", "Django", "Persists imported data to Database")
    }

    Rel(web_app, import_controller, "Triggers import", "async")
    UpdateRelStyle(web_app, import_controller, $textColor="blue", $lineColor="blue", $offsetX="-50", $offsetY="-170")

    Rel(import_controller, file_reader, "Reads file data")
    UpdateRelStyle(import_controller, file_reader, $textColor="purple", $lineColor="purple", $offsetX="-40", $offsetY="10")

    Rel(import_controller, api_fetcher, "Fetches API data")
    UpdateRelStyle(import_controller, api_fetcher, $textColor="purple", $lineColor="purple", $offsetX="110", $offsetY="-10")

    Rel(file_reader, mapping_importer, "Sends parsed file data")
    UpdateRelStyle(file_reader, mapping_importer, $textColor="purple", $lineColor="purple", $offsetX="-30", $offsetY="0")

    Rel(api_fetcher, mapping_importer, "Sends API data")
    UpdateRelStyle(api_fetcher, mapping_importer, $textColor="purple", $lineColor="purple", $offsetX="0", $offsetY="0")

    Rel(mapping_importer, validation_component, "Validates<br>mapped data")
    UpdateRelStyle(mapping_importer, validation_component, $textColor="purple", $lineColor="purple", $offsetX="-40", $offsetY="-20")

    Rel(validation_component, repository, "Persists valid data")
    UpdateRelStyle(validation_component, repository, $textColor="purple", $lineColor="purple", $offsetX="-50", $offsetY="-20")

    Rel(repository, database, "Reads/Writes", "SQL")
    UpdateRelStyle(repository, database, $textColor="gray", $lineColor="gray", $offsetX="0", $offsetY="-30")

    Rel(file_reader, xlsx_files, "Reads XLSX files", "File I/O")
    UpdateRelStyle(file_reader, xlsx_files, $textColor="purple", $lineColor="purple", $offsetX="-20", $offsetY="60")

    Rel(api_fetcher, aurora_api, "Fetches data", "REST/JSON")
    UpdateRelStyle(api_fetcher, aurora_api, $textColor="purple", $lineColor="purple", $offsetX="-20",$offsetY="0")

    Rel(api_fetcher, kobo_api, "Fetches data", "REST/JSON")
    UpdateRelStyle(api_fetcher, kobo_api, $textColor="purple", $lineColor="purple", $offsetX="-100",$offsetY="-50")

    UpdateElementStyle(web_app, $bgColor="lightblue", $fontColor="black", $borderColor="blue")

    UpdateElementStyle(import_controller, $bgColor="thistle", $fontColor="black", $borderColor="purple")
    UpdateElementStyle(file_reader, $bgColor="thistle", $fontColor="black", $borderColor="purple")
    UpdateElementStyle(api_fetcher, $bgColor="thistle", $fontColor="black", $borderColor="purple")
    UpdateElementStyle(mapping_importer, $bgColor="thistle", $fontColor="black", $borderColor="purple")
    UpdateElementStyle(validation_component, $bgColor="thistle", $fontColor="black", $borderColor="purple")
    UpdateElementStyle(repository, $bgColor="thistle", $fontColor="black", $borderColor="purple")

    UpdateElementStyle(database, $bgColor="lightgray", $fontColor="black", $borderColor="gray")

    UpdateElementStyle(aurora_api, $bgColor="lavender", $fontColor="black", $borderColor="slateblue")
    UpdateElementStyle(kobo_api, $bgColor="lavender", $fontColor="black", $borderColor="slateblue")
    UpdateElementStyle(xlsx_files, $bgColor="lavender", $fontColor="black", $borderColor="slateblue")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")


```
