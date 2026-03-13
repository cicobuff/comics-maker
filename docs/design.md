# Comics Maker

## Introduction
This is a project that creates an app for Comics creation and exporting.

## Platform

* the project will be built for linux environments with gtk 4
* language will be python
* graphics library will be Cairo
* gui library will be gtk 4.0
* text rendering will be pillow

## GUI Design

* the UX flow consist of the following screens
  * initial setup_screen where the following configuration is set and saved
    * the global settings directory, defaulted to ~/.comicsmaker, the file is config.json
    * the projects directory, defaulted to ~/Documents/ComicsMaker
    * the setup_screen is only displayed when the global settings directory and file comicsmaker.conf is not present
  * upon app launch, the projects_screen is displayed
    * the projects screen show the different projects that have been saved in the projects directory
    * the projects screen allows selection, deletion and creating of projects
  * once a project is selected or created, the project_workspace screen is displayed
    * the project_workspace consist of the following layout
      * a menu bar at the top
      * a toolbar at the top
      * a collapsable left panel showing the pages of the comic project, this is the page_panel
        * there should be a add page button to add new pages
        * pages can be deleted by selecting it on the page_panel and clicking on the delete button
        * pages can be duplicated by selecting it on the page_panel and clicking on the duplicate button
        * pages can be reordered clicking and dragging them up and down the page_panel in the order as they appear
      * a center work_area that displays the current selected page that is being worked on
      * a collapsable right panel that will contain elements that can be dragged and dropped into the work_area, this is the elements_panel
        * the elements panel have a hidden element_properties_panel that will appear when elements are selected
          * the elements property panel will contain settings for text, font, color (color chooser), background color
          * elements fill should allow for a gradient fill as well as plain color fill
    * the work_area can represent a page that can be zoomed in and out 
      * each comic page can contain multiple comic_panels
      * each comic_panel can contain a single image, when another image is dropped into the comic_panel, the existing image will be replaced with the new one
      * when an image is dropped into the comic_panel, the image displayed is resized to fill the comic_panel
    * every element that is added into the work_area can be click on and the user is allowed to resize the added elements
      * for images, this needs special handling, when resizing, keep the original aspect ratio
      * all other elements can be stretch and resized without honoring the aspect ratio
      * users can delete elements after adding them
      * users can rotate the elements, this can be done with both a rotate handle on selection and as part of the elements property panel options
      * for text handling, use a model panel that pops up, but do realtime rendering updates to the work_area when the text properties are edited
      * elements should be managed via layers so that they can be ordered with ordering functions, backward, forward, bring to front and bring to back
  * there is an export button on the toolbar as well as a menuitem on the menu on the menubar
    * the export can be done in cbz or pdf format
  * the elements_panel should contain
    * comics_panels
    * shapes, shapes are common vector components that come in circle, pentagon, square, rectangles, triangles 
    * textarea, texts are that can be added to the page for text addition, it consists of a box with text in it and the fonts and colors and background colors can be independently selected
    * speech_bubbles, are special shapes in vector graphics that are shaped like comic book speech bubbles

## Shapes Design

* each shape should be fully described in a json format where each shape's coordinates and line color and line weight and background color can be fully described
  * the shapes can be stored in a shapes directory which can then be extended with more shapes later
* speech_bubbles should also be fully described in a json format where the speech bubble's shape information and the text offset and the text color, size, color, font can be described 
  * the speech_bubbles can be stored in a speech_bubbles directory that can be extended later

## Project Persistence Design

* each project can be saved and loaded
  * each project is saved as a folder ending with suffix .comicmaker
  * in each project folder, there is a project.comic in json format file that saves all the project details
  * in each project folder, there will be a images folder that holds the original images that have been added to the project via the work_area
    * when images are added, the image is first copied to the project images folder and then the app will reference the copied images, the copied images should use uuid as their names to avoid conflicts
    * there will be a thumb folder if the app generates thumbnails for display purposes
  * each project can be restored to exactly what it was at the time of save by reading the project folder and the project.comic
  * when a project is opened, it will spawn another project_workspace that can work independently of other opened project_workspace

## Quality of Life Features

* support for undo and redo up to 999 steps, the maximum can be configured in the global settings
* there should be a settings dialog that can be accessed from the menu
* the drag and drop of images should support dragging images from web browsers as well as from file browsers on GTK
* the project selection should support creation of project with templates
  * templates should have default page resolution and size
* when exporting, users should be able to select resolution, quality, page range
  * there should also be an option to compress images from the native imported resolution to best fit their sizes in the panels
    * the compression should only affect exported images but keep the original image unmodified
* PNG must be supported, JPEG and SVG formats can be added later
* there should be a facility for managing grids and snap to grids when moving elements
  * the default grid size should be 20 pixels
  * there should be a toggle for visible gird on the toolbar and in the menu under view
* there should be confirmation dialog for deletion of projects, pages and elements 

## Zoom Controls

* when the cursor is in the work_area, use the scrollwheel of the mouse for zoom controls
* also use the shortcut ctrl+ and ctrl- for zoom
* the minimum zoom is 10% or 100 pixels
* the maximum zoom is 800% 
* the maximum and minimum zoom should be configurable in global settings
* the scroll zoom step should be 10%, this should be configurable in global settings

## Menubar structure

* File -> New Project/Open/Save/Save As.../Export/Settings/Quit
* Edit -> Undo/Redo/Copy/Paste
* View -> Zoom In/Zoom Out/Full Page/Page Width

## Toolbar buttons

* Save/Undo/Redo/Zoom Controls/Export

## Default Page Dimensions

* The default page dimensions should come from a default project template that is stored in the templates directory, the template should be a json file
* The default page dimensions should be 1536 x 2048 

## Save Behavior

* The save should be done manually via the menu or toolbar

## Copy/paste/cut functionality

* Elements can be copied across pages and even projects, when multiple projects are open

## Fonts

* Fonts should be kept in the fonts directory so that they can be added later. use ttf
* Please include Comic Sans, Arial initially, more can be added later

## Element Properties

* Elements properties should be managed from a property panel that appear on the right, it will appear on the top of the elements panel
  * the properties panel will hide itself when no element is selected

## Multi-selection

* Pages can be multi-select, deletion and ordering can be done with multi-select
* Elements in a page can multi-selected, when another element in another page is selected, the previous multi-select is canceled

## Image formats

* the user can drag images from web browsers to the work_area
  * if they fall into any comic_panel, then the image will be placed inside the comic_panel which will control the display boundaries of the image, the image should be resized to best fit the panel
  * if they all outside any comic_panel, then a comic_panel will be created at the dropped location and the image will be placed inside the comic_panel, the size of the created comic_panel should be 20% of the size of the page
* the user can also drag an image file directly to the work_area from the file browser, only single image can be dragged
* the user can also copy and paste the image from the browser into the work_area at the position of the cursor, if the cursor is outside the work_area boundaries, the comic_panel will be centered on the page
* for image formats that are not native to the app, please do conversion so that the app can work

## Default placeholder text

* textareas and speech bubbles should have "Enter text here" as starting text

## Comic pan/seel borders 

* Comic panel borders should be configurable with reasonable defaults in config.json

## Selection visualization

* This should be configurable in config.json, defaulted to blue bounding box with 8 resize handles at corners and edges, dotted outline

