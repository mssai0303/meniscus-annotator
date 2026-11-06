# Build-time installation into Slicer's bundled Python; never run on Jeff's machine.
set(proj python-meniscus-requirements)
set(${proj}_DEPENDENCIES python python-numpy python-pip python-pythonqt-requirements)
ExternalProject_Include_Dependencies(${proj} PROJECT_VAR proj DEPENDS_VAR ${proj}_DEPENDENCIES)
set(requirements_file "${CMAKE_BINARY_DIR}/${proj}-requirements.txt")
file(WRITE "${requirements_file}" [===[
nibabel==5.3.2 --hash=sha256:52970a5a8a53b1b55249cba4d9bcfaa8cc57e3e5af35a29d7352237e8680a6f8
typing_extensions==4.15.0 --hash=sha256:f0fa19c6845758ab08074a0cfa8b7aecb71c999ca73d62883bc25cc018c4e548
]===])
ExternalProject_Add(${proj}
  ${${proj}_EP_ARGS}
  DOWNLOAD_COMMAND ""
  SOURCE_DIR "${CMAKE_BINARY_DIR}/${proj}"
  BUILD_IN_SOURCE 1
  CONFIGURE_COMMAND ""
  BUILD_COMMAND ""
  INSTALL_COMMAND "${PYTHON_EXECUTABLE}" -m pip install --only-binary=:all: --no-deps --require-hashes -r "${requirements_file}"
  LOG_INSTALL 1
  DEPENDS ${${proj}_DEPENDENCIES})
