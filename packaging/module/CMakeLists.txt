# Compile/copy only application code; data and private logs are never packaged.
get_filename_component(MENISCUS_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../.." ABSOLUTE)
file(GLOB_RECURSE MENISCUS_LIB_SCRIPTS CONFIGURE_DEPENDS
  RELATIVE "${MENISCUS_SOURCE_DIR}" "${MENISCUS_SOURCE_DIR}/MeniscusAnnotatorLib/*.py")
ctkMacroCompilePythonScript(
  TARGET_NAME MeniscusAnnotator
  SOURCE_DIR "${MENISCUS_SOURCE_DIR}"
  SCRIPTS MeniscusAnnotator.py ${MENISCUS_LIB_SCRIPTS}
  DESTINATION_DIR "${CMAKE_BINARY_DIR}/${Slicer_QTSCRIPTEDMODULES_LIB_DIR}"
  INSTALL_DIR "${Slicer_INSTALL_QTSCRIPTEDMODULES_LIB_DIR}"
  NO_INSTALL_SUBDIR)
install(FILES "${MENISCUS_SOURCE_DIR}/LICENSE" "${MENISCUS_SOURCE_DIR}/packaging/TEMPLATE_NOTICE.txt"
  DESTINATION "share/MeniscusAnnotator/licenses" COMPONENT Runtime)
install(DIRECTORY "${MENISCUS_SOURCE_DIR}/packaging/licenses/"
  DESTINATION "share/MeniscusAnnotator/licenses" COMPONENT Runtime)
