# JLCPCB KiCad Integration Plugin - Agentic Implementation Plan

## Project Overview
Develop a KiCad plugin that enables seamless import of JLCPCB/LCSC parts directly into schematics with automatic symbol, footprint, and 3D model generation.

---

## Phase 1: Environment Setup & Requirements Analysis

### 1.1 Development Environment
- **Task**: Set up Python development environment for KiCad plugin development
- **Requirements**:
  - Python 3.9+ (match KiCad's Python version)
  - KiCad 8.0+ installed with Python scripting enabled
  - Virtual environment for dependency management
- **Deliverables**:
  - `requirements.txt` with dependencies: `requests`, `wxPython`, `beautifulsoup4`, `Pillow`
  - Development directory structure initialized
  - Test that KiCad Python console can import custom modules

### 1.2 Analyze Existing Script
- **Task**: Reverse-engineer the current JLC2KiCad script functionality
- **Questions to Answer**:
  - What API endpoints does it use? (JLCPCB/LCSC/EasyEDA)
  - How does it parse component data?
  - What file formats does it generate? (`.kicad_sym`, `.kicad_mod`, `.step`/`.wrl`)
  - Are there rate limits or authentication requirements?
  - What's the data structure of API responses?
- **Deliverables**:
  - API endpoint documentation
  - Sample API responses saved as JSON fixtures
  - Mapping of LCSC part data → KiCad symbol/footprint elements

### 1.3 KiCad API Research
- **Task**: Document KiCad's Python API capabilities for schematic manipulation
- **Focus Areas**:
  - `eeschema` module capabilities (KiCad 8.0)
  - Symbol creation and placement APIs
  - Library table manipulation
  - Footprint assignment methods
  - Cursor position detection
  - Undo/redo integration
- **Deliverables**:
  - API capability matrix (what's possible vs. not)
  - Code snippets for each required operation
  - Limitations document

---

## Phase 2: Core Architecture Design

### 2.1 Module Structure
```
jlcpcb_importer/
├── __init__.py                 # Plugin registration
├── plugin.py                   # Main ActionPlugin class
├── api/
│   ├── __init__.py
│   ├── jlcpcb_client.py       # API client for JLCPCB/LCSC
│   └── cache.py               # Local caching to reduce API calls
├── generators/
│   ├── __init__.py
│   ├── symbol_generator.py    # KiCad symbol generation
│   ├── footprint_generator.py # KiCad footprint generation
│   └── model_3d_generator.py  # 3D model handling
├── ui/
│   ├── __init__.py
│   ├── import_dialog.py       # Main import dialog
│   └── preview_panel.py       # Component preview rendering
├── library/
│   ├── __init__.py
│   ├── manager.py             # Library path management
│   └── table_editor.py        # sym-lib-table/fp-lib-table manipulation
└── utils/
    ├── __init__.py
    ├── logger.py              # Logging configuration
    └── config.py              # Plugin configuration
```

### 2.2 Data Flow Architecture
```
User Input (LCSC#) 
    → API Client (fetch part data)
    → Cache Check (avoid redundant calls)
    → Preview Dialog (show component info)
    → User Confirms
    → Generator Pipeline:
        1. Create symbol file in project/jlcpcb_lib/symbols/
        2. Create footprint file in project/jlcpcb_lib/footprints/
        3. Download/generate 3D model in project/jlcpcb_lib/3dmodels/
        4. Update library tables (sym-lib-table, fp-lib-table)
        5. Place symbol in schematic with footprint pre-assigned
    → Update schematic view
```

### 2.3 Configuration System
- **Task**: Define plugin configuration strategy
- **Configuration Items**:
  - API endpoints and rate limit settings
  - Cache expiration policy
  - Library directory naming scheme
  - Default 3D model download behavior (always/ask/never)
  - Preview image resolution
  - Component field mapping preferences
- **Deliverables**:
  - `config.json` schema
  - Config loading/saving module
  - UI for config editing (optional, can use JSON directly)

---

## Phase 3: API Integration Layer

### 3.1 JLCPCB/LCSC API Client
- **Task**: Implement robust API client with error handling
- **Requirements**:
  ```python
  class JLCPCBClient:
      def search_part(self, lcsc_number: str) -> PartData
      def get_component_details(self, lcsc_number: str) -> ComponentDetails
      def download_footprint_data(self, part_id: str) -> FootprintData
      def download_symbol_data(self, part_id: str) -> SymbolData
      def download_3d_model(self, part_id: str, format: str) -> bytes
  ```
- **Error Handling**:
  - Network timeouts (retry with exponential backoff)
  - Invalid part numbers (clear error message)
  - API rate limiting (respect limits, queue requests)
  - Malformed responses (graceful degradation)
- **Deliverables**:
  - `jlcpcb_client.py` with full implementation
  - Unit tests with mocked responses
  - API documentation comments

### 3.2 Caching System
- **Task**: Implement local cache to minimize API calls
- **Strategy**:
  - SQLite database for structured data
  - Filesystem for binary data (3D models, preview images)
  - Cache key: LCSC part number + data type
  - TTL: 30 days for part data, indefinite for models
- **Schema**:
  ```sql
  CREATE TABLE part_cache (
      lcsc_number TEXT PRIMARY KEY,
      data JSON,
      timestamp INTEGER,
      last_accessed INTEGER
  );
  ```
- **Deliverables**:
  - `cache.py` implementation
  - Cache cleanup routine (remove stale entries)
  - Cache statistics tracking

### 3.3 Data Models
- **Task**: Define Python dataclasses for API responses
- **Models Needed**:
  ```python
  @dataclass
  class PartData:
      lcsc_number: str
      manufacturer: str
      mpn: str  # Manufacturer part number
      description: str
      package: str
      datasheet_url: str
      price: List[PriceBreak]
      stock: int
      attributes: Dict[str, str]
  
  @dataclass
  class FootprintData:
      pads: List[Pad]
      silkscreen: List[GraphicElement]
      courtyard: List[GraphicElement]
      fab_layer: List[GraphicElement]
  
  @dataclass
  class SymbolData:
      pins: List[Pin]
      body: List[GraphicElement]
      fields: Dict[str, str]
  ```
- **Deliverables**:
  - Complete dataclass definitions
  - JSON serialization/deserialization methods
  - Validation logic

---

## Phase 4: Generator Implementation

### 4.1 Symbol Generator
- **Task**: Convert JLCPCB symbol data to KiCad `.kicad_sym` format
- **Requirements**:
  - Parse pin data (number, name, electrical type, position)
  - Generate symbol body graphics (rectangle, text labels)
  - Set standard fields (Reference, Value, Footprint, Datasheet)
  - Add custom fields (LCSC#, Manufacturer, MPN)
  - Handle multi-unit symbols (if applicable)
- **KiCad Symbol Structure**:
  ```
  (kicad_symbol_lib (version 20231120) (generator jlcpcb_importer)
    (symbol "C12345" (pin_names (offset 0.254))
      (property "Reference" "U" ...)
      (property "Value" "STM32F103C8T6" ...)
      (property "Footprint" "Package_QFP:LQFP-48_7x7mm_P0.5mm" ...)
      (property "LCSC" "C12345" ...)
      (symbol "C12345_0_1" ... )
    )
  )
  ```
- **Deliverables**:
  - `symbol_generator.py` with S-expression builder
  - Template-based generation for common IC types
  - Unit tests comparing generated vs. expected output

### 4.2 Footprint Generator
- **Task**: Convert JLCPCB footprint data to KiCad `.kicad_mod` format
- **Requirements**:
  - Generate pads with correct:
    - Position, size, shape (rect/oval/circle)
    - Pad type (SMD/THT)
    - Pad number
    - Layers (F.Cu, F.Mask, F.Paste)
  - Generate silkscreen outline
  - Generate courtyard (IPC-compliant expansion)
  - Add 3D model reference
  - Set footprint properties (description, tags, attributes)
- **Special Cases**:
  - BGA footprints (array generation)
  - Castellated holes
  - Thermal pads
  - Complex pad shapes
- **Deliverables**:
  - `footprint_generator.py` implementation
  - Footprint validation (DRC-compliant)
  - Support for standard packages (QFP, SOIC, 0402, 0603, etc.)

### 4.3 3D Model Handler
- **Task**: Download and integrate 3D models
- **Requirements**:
  - Download STEP/WRL models from JLCPCB/EasyEDA
  - Convert formats if needed (STEP → WRL using external tools)
  - Scale and position model correctly
  - Handle missing models gracefully (use generic placeholder?)
- **Model Naming Convention**:
  - `{LCSC_number}.step` or `{LCSC_number}.wrl`
  - Store in `project/jlcpcb_lib/3dmodels/`
- **Deliverables**:
  - `model_3d_generator.py` implementation
  - Model download with progress indication
  - Fallback strategy for unavailable models

---

## Phase 5: Library Management

### 5.1 Library Path Manager
- **Task**: Create/manage project-specific library directories
- **Requirements**:
  - Detect project root from open schematic
  - Create `jlcpcb_lib/` structure if not exists:
    ```
    jlcpcb_lib/
    ├── symbols/
    │   └── jlcpcb_parts.kicad_sym
    ├── footprints.pretty/
    │   ├── C12345.kicad_mod
    │   └── C67890.kicad_mod
    └── 3dmodels/
        ├── C12345.step
        └── C67890.step
    ```
  - Handle relative vs. absolute paths
  - Verify write permissions
- **Deliverables**:
  - `library/manager.py` with path utilities
  - Path resolution logic (handle Windows/Linux/macOS)
  - Error handling for permission issues

### 5.2 Library Table Editor
- **Task**: Programmatically update KiCad library tables
- **Requirements**:
  - Parse `sym-lib-table` and `fp-lib-table` (S-expression format)
  - Add library entries if not present:
    ```
    (lib (name "JLCPCB_Parts")(type "KiCad")(uri "${KIPRJMOD}/jlcpcb_lib/symbols/jlcpcb_parts.kicad_sym")(options "")(descr "JLCPCB imported parts"))
    ```
  - Update existing entries if paths changed
  - Preserve existing libraries (don't corrupt table)
  - Backup tables before modification
- **Safety**:
  - Validate S-expression syntax before writing
  - Atomic file operations (write to temp, then rename)
  - Rollback capability on errors
- **Deliverables**:
  - `library/table_editor.py` implementation
  - Parser for S-expression format
  - Unit tests with sample library tables

### 5.3 Symbol Appending
- **Task**: Add generated symbols to library file
- **Requirements**:
  - Load existing `.kicad_sym` file
  - Check for duplicate symbols (same LCSC number)
  - Append new symbol definition
  - Maintain file formatting
- **Conflict Resolution**:
  - If symbol exists: ask user (replace/skip/rename)
  - Version tracking (optional)
- **Deliverables**:
  - Symbol library file manager
  - Merge logic with conflict handling

---

## Phase 6: User Interface

### 6.1 Main Import Dialog
- **Task**: Create wxPython dialog for part import
- **UI Layout**:
  ```
  ┌─────────────────────────────────────────┐
  │  Import JLCPCB Component                │
  ├─────────────────────────────────────────┤
  │  LCSC Part Number: [____________] [Fetch]│
  │                                          │
  │  ┌────────────────────────────────────┐ │
  │  │ Preview:                           │ │
  │  │                                    │ │
  │  │  [Component Image]                 │ │
  │  │                                    │ │
  │  │  Name: STM32F103C8T6              │ │
  │  │  Package: LQFP-48                  │ │
  │  │  Manufacturer: STMicroelectronics  │ │
  │  │  Description: ...                  │ │
  │  │  Stock: 12,456                     │ │
  │  │  Price: $2.15 @ 100pcs             │ │
  │  └────────────────────────────────────┘ │
  │                                          │
  │  Options:                                │
  │  [✓] Download 3D model                   │
  │  [✓] Place in schematic immediately      │
  │                                          │
  │              [Import] [Cancel]           │
  └─────────────────────────────────────────┘
  ```
- **Features**:
  - Paste LCSC number and hit Enter to fetch
  - Live preview with image (if available)
  - Show stock/pricing info
  - Progress bar during download
  - Error messages in status bar
- **Deliverables**:
  - `ui/import_dialog.py` with full layout
  - Event handlers for all buttons
  - Input validation (LCSC format: C######)

### 6.2 Preview Panel
- **Task**: Render component preview with image and details
- **Requirements**:
  - Fetch preview image from JLCPCB (if available)
  - Display component specifications in formatted text
  - Show footprint outline preview (optional enhancement)
  - Highlight key specifications (voltage, current, package)
- **Deliverables**:
  - `ui/preview_panel.py` implementation
  - Image caching for faster subsequent loads
  - Fallback for missing images (show placeholder)

### 6.3 Configuration Dialog (Optional)
- **Task**: Settings dialog for plugin configuration
- **Settings to Expose**:
  - API endpoint URLs (for custom servers)
  - Cache directory location
  - Cache expiration time
  - Default 3D model behavior
  - Library naming preferences
- **Deliverables**:
  - Settings dialog accessible from plugin menu
  - Persist settings to config file

---

## Phase 7: Schematic Integration

### 7.1 Symbol Placement
- **Task**: Place generated symbol in schematic at cursor position
- **Requirements**:
  - Get current cursor position in schematic coordinates
  - Create symbol instance from library reference
  - Set footprint field to generated footprint
  - Set additional fields (LCSC#, manufacturer, MPN, datasheet URL)
  - Add symbol to schematic sheet
  - Refresh schematic view
- **KiCad API Calls**:
  ```python
  schematic = eeschema.GetSchematicFrame()
  sheet = schematic.GetCurrentSheet()
  cursor_pos = schematic.GetCursorPosition()
  
  # Create symbol instance
  symbol = eeschema.SCH_SYMBOL()
  symbol.SetLibId("JLCPCB_Parts:C12345")
  symbol.SetPosition(cursor_pos)
  symbol.SetFootprintFieldText("JLCPCB_Footprints:C12345")
  
  # Add fields
  symbol.AddField(eeschema.SCH_FIELD("LCSC", "C12345"))
  symbol.AddField(eeschema.SCH_FIELD("Manufacturer", "STMicro"))
  
  # Add to schematic
  sheet.AddSymbol(symbol)
  schematic.RefreshCanvas()
  ```
- **Challenges**:
  - Verify API availability in KiCad 8.0
  - Handle undo/redo integration
  - Proper unit selection for multi-unit symbols
- **Deliverables**:
  - Symbol placement function
  - Integration test with real schematic

### 7.2 Reference Designator Handling
- **Task**: Auto-increment reference designators
- **Requirements**:
  - Detect next available reference (e.g., U1, U2, U3...)
  - Use appropriate prefix based on component type:
    - Resistors: R
    - Capacitors: C
    - ICs: U
    - Connectors: J
    - LEDs: D
  - Avoid conflicts with existing components
- **Deliverables**:
  - Reference designator assignment logic
  - Type detection based on component attributes

### 7.3 Undo/Redo Integration
- **Task**: Ensure plugin actions are undo-able
- **Requirements**:
  - Wrap symbol placement in undo/redo transaction
  - Library file changes should be atomic
  - Document limitations (library table changes may not be undoable)
- **Deliverables**:
  - Transaction-wrapped operations
  - Documentation of undo behavior

---

## Phase 8: Error Handling & Validation

### 8.1 Network Error Handling
- **Scenarios**:
  - No internet connection
  - API server down
  - Timeout during large file download
  - Invalid SSL certificates
  - Rate limiting
- **Responses**:
  - Clear error messages to user
  - Retry logic with exponential backoff
  - Cache fallback (use cached data if available)
  - Graceful degradation (continue without 3D model)
- **Deliverables**:
  - Comprehensive try/except blocks
  - User-friendly error dialogs
  - Logging of all errors

### 8.2 Data Validation
- **Validation Points**:
  - LCSC number format (C followed by digits)
  - API response completeness
  - Generated file syntax (valid S-expressions)
  - Footprint DRC compliance
  - Symbol pin connectivity
- **Deliverables**:
  - Validation functions for each data type
  - Unit tests for validation logic

### 8.3 File System Safety
- **Safeguards**:
  - Check write permissions before generating files
  - Backup existing files before overwriting
  - Use atomic file operations (temp → rename)
  - Handle disk full scenarios
  - Clean up temp files on error
- **Deliverables**:
  - Safe file writing utilities
  - Cleanup routines in exception handlers

---

## Phase 9: Testing Strategy

### 9.1 Unit Tests
- **Coverage**:
  - API client with mocked responses
  - Symbol/footprint generators with known inputs
  - Library table parser/editor
  - Data validation functions
  - Configuration loading/saving
- **Framework**: `pytest`
- **Target**: >85% code coverage
- **Deliverables**:
  - `tests/` directory with full test suite
  - CI integration (GitHub Actions)
  - Test fixtures for API responses

### 9.2 Integration Tests
- **Test Scenarios**:
  1. End-to-end: LCSC number → symbol in schematic
  2. Library creation from scratch
  3. Adding to existing library
  4. Handling duplicate parts
  5. Error recovery (network failure mid-download)
  6. Multiple parts in single session
- **Environment**: Test KiCad project with known state
- **Deliverables**:
  - Integration test suite
  - Test project files in repository

### 9.3 Manual Testing Checklist
- [ ] Install plugin in clean KiCad installation
- [ ] Import resistor (C25804)
- [ ] Import capacitor (C1525)
- [ ] Import IC (C8734)
- [ ] Import connector
- [ ] Import component with 3D model
- [ ] Import component without 3D model
- [ ] Import duplicate component (verify conflict handling)
- [ ] Test with no internet connection
- [ ] Test with invalid LCSC number
- [ ] Verify generated symbols are electrically correct
- [ ] Verify footprints pass DRC
- [ ] Verify 3D models display correctly in 3D viewer
- [ ] Test undo/redo of symbol placement
- [ ] Verify library tables updated correctly

---

## Phase 10: Documentation & Packaging

### 10.1 User Documentation
- **README.md Contents**:
  - Installation instructions (manual + KiCad PCM)
  - Quick start guide with screenshots
  - Supported features and limitations
  - Troubleshooting common issues
  - FAQ section
  - License information
- **In-App Help**:
  - Tooltips on all UI elements
  - Help button → opens documentation
- **Deliverables**:
  - Complete README.md
  - Screenshots and GIFs of plugin in action
  - Video tutorial (optional)

### 10.2 Developer Documentation
- **API Documentation**:
  - Docstrings for all public functions
  - Architecture diagrams
  - Data flow diagrams
  - Extension points for future features
- **Contributing Guide**:
  - Code style guidelines
  - How to set up dev environment
  - How to run tests
  - Pull request process
- **Deliverables**:
  - `docs/` directory with Markdown files
  - Auto-generated API docs (Sphinx/mkdocs)

### 10.3 KiCad PCM Packaging
- **Requirements**:
  - `metadata.json` for Plugin and Content Manager
  - Icon file (PNG, 64x64)
  - Screenshots for PCM listing
  - Version numbering scheme (semantic versioning)
  - Change log
- **Metadata Example**:
  ```json
  {
    "name": "JLCPCB Component Importer",
    "description": "Import components from JLCPCB/LCSC directly into schematics",
    "identifier": "com.github.yourusername.jlcpcb_importer",
    "type": "plugin",
    "author": {
      "name": "Your Name",
      "contact": { "web": "https://github.com/..." }
    },
    "maintainer": { ... },
    "license": "MIT",
    "resources": {
      "homepage": "https://github.com/.../jlcpcb_importer"
    },
    "versions": [
      {
        "version": "1.0.0",
        "status": "stable",
        "kicad_version": "8.0",
        "download_url": "...",
        "install_size": 512000
      }
    ]
  }
  ```
- **Deliverables**:
  - Complete PCM package
  - Submission to KiCad PCM repository

---

## Phase 11: Optimization & Polish

### 11.1 Performance Optimization
- **Targets**:
  - API response caching reduces latency by >90%
  - Symbol generation <500ms
  - Footprint generation <1s
  - UI remains responsive during downloads (threading)
- **Optimizations**:
  - Parallel downloads (3D model + preview image)
  - Lazy loading of library files
  - Efficient S-expression parsing
  - Database indexing for cache
- **Deliverables**:
  - Performance benchmarks
  - Profiling results and optimization notes

### 11.2 User Experience Enhancements
- **Polish Items**:
  - Keyboard shortcuts (Enter to fetch, Ctrl+Enter to import)
  - Recent parts history (dropdown with last 10 searches)
  - Favorite parts list
  - Batch import mode (import multiple parts from CSV)
  - Dark mode support for dialogs
  - Progress notifications for long operations
- **Deliverables**:
  - Enhanced UI with all polish items
  - User preferences for UX settings

### 11.3 Advanced Features (Future)
- **Ideas for v2.0+**:
  - BOM integration (import all parts from BOM file)
  - Alternative parts suggestions
  - Price comparison across distributors
  - Parametric search (filter by specs)
  - Auto-routing hints based on part type
  - Integration with JLCPCB assembly service
  - Cloud library sync across projects

---

## Phase 12: Release & Maintenance

---

## Success Criteria

### Minimum Viable Product (MVP)
- [ ] User can paste LCSC number and import component
- [ ] Symbol, footprint, and 3D model generated correctly
- [ ] Component placed in schematic with footprint assigned
- [ ] Works on Windows, Linux, and macOS
- [ ] No data loss or file corruption
- [ ] Basic error handling for network issues

### Complete Feature Set
- [ ] All MVP criteria met
- [ ] Preview dialog with component images
- [ ] Caching system functional
- [ ] Project-specific library management
- [ ] KiCad PCM distribution
- [ ] Comprehensive documentation
- [ ] >85% test coverage

### Excellence Indicators
- [ ] Sub-second response time for cached parts
- [ ] Zero crashes in normal operation
- [ ] Positive user reviews on KiCad forums
- [ ] Active community contributions
- [ ] Featured in KiCad newsletter/blog

---

## Risk Mitigation

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| JLCPCB API changes | Medium | High | Abstract API layer; version detection; fallback to web scraping |
| KiCad API limitations | High | High | Early prototyping; document workarounds; fallback to file manipulation |
| File corruption | Low | Critical | Atomic operations; backups; extensive testing |
| Legal issues (API ToS) | Low | High | Review JLCPCB ToS; consider official partnership; respect rate limits |
| Performance issues | Medium | Medium | Profiling; caching; async operations |

---

## Timeline Estimate

- **Phase 1-2**: 1 week (setup + architecture)
- **Phase 3-4**: 2 weeks (API + generators)
- **Phase 5-7**: 2 weeks (library management + schematic integration)
- **Phase 8-9**: 1 week (error handling + testing)
- **Phase 10-11**: 1 week (documentation + polish)
- **Phase 12**: Ongoing (release + maintenance)

**Total Development Time**: ~7-8 weeks for complete v1.0 release

---



## Additional Resources

### Useful Links
- KiCad Python API Documentation: https://docs.kicad.org/doxygen-python/
- KiCad Plugin Examples: https://gitlab.com/kicad/code/kicad/-/tree/master/scripting/plugins
- JLCPCB Parts Library: https://jlcpcb.com/parts
- LCSC Component Search: https://lcsc.com/
- KiCad PCM Submission Guide: https://gitlab.com/kicad/addons/metadata

### Key Technical References
- S-expression format specification
- KiCad file format documentation
- IPC footprint standards
- wxPython documentation

---

*Document Version: 1.0*
*Last Updated: 2026-01-29*
*Author: Implementation plan for agentic coding agent*
