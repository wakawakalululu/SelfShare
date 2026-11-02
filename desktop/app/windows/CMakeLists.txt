cmake_minimum_required(VERSION 3.14)
project(selfshare_desktop LANGUAGES CXX)

set(BINARY_NAME "selfshare_desktop")
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(FLUTTER_MANAGED_DIR "${CMAKE_CURRENT_SOURCE_DIR}/flutter")
include(${FLUTTER_MANAGED_DIR}/generated_config.cmake)

set(FLUTTER_EPHEMERAL_DIR "${FLUTTER_MANAGED_DIR}/ephemeral")
add_subdirectory(${FLUTTER_EPHEMERAL_DIR})

add_executable(${BINARY_NAME} WIN32
  "runner/main.cpp"
  "runner/flutter_window.cpp"
  "runner/utils.cpp"
  "runner/win32_window.cpp"
  "runner/Runner.rc"
  "runner/resources/app_icon.ico"
)
apply_standard_settings(${BINARY_NAME})
target_compile_definitions(${BINARY_NAME} PRIVATE "UNICODE" "_UNICODE")
target_link_libraries(${BINARY_NAME} PRIVATE flutter flutter_wrapper_app)
target_include_directories(${BINARY_NAME} PRIVATE "${CMAKE_SOURCE_DIR}")
add_dependencies(${BINARY_NAME} flutter_assemble)

include(flutter/generated_plugins.cmake)

set(BUILD_BUNDLE_DIR "$<TARGET_FILE_DIR:${BINARY_NAME}>")
set(INSTALL_BUNDLE_DATA_DIR "${BUILD_BUNDLE_DIR}/data")
set(INSTALL_BUNDLE_LIB_DIR "${BUILD_BUNDLE_DIR}")

install(TARGETS ${BINARY_NAME} RUNTIME DESTINATION "${CMAKE_INSTALL_PREFIX}")
install(FILES "${FLUTTER_ICU_DATA_FILE}" DESTINATION "${INSTALL_BUNDLE_DATA_DIR}")
install(FILES "${FLUTTER_LIBRARY}" DESTINATION "${INSTALL_BUNDLE_LIB_DIR}")
install(DIRECTORY "${PROJECT_BUILD_DIR}/${FLUTTER_ASSET_DIR_NAME}"
  DESTINATION "${INSTALL_BUNDLE_DATA_DIR}")
install(FILES "${AOT_LIBRARY}" DESTINATION "${INSTALL_BUNDLE_DATA_DIR}"
  CONFIGURATIONS Profile;Release COMPONENT Runtime)

# Rust 同步内核：build_windows.ps1 会先产出此 DLL。
# 自动按 build 类型选 release 或 debug，最后回退到 ../core/target/release。
set(SELFSHARE_CORE_DLL "${CMAKE_CURRENT_SOURCE_DIR}/../core/target/release/selfshare_core.dll")
if(NOT EXISTS "${SELFSHARE_CORE_DLL}")
  set(SELFSHARE_CORE_DLL "${CMAKE_CURRENT_SOURCE_DIR}/../core/target/debug/selfshare_core.dll")
endif()
if(EXISTS "${SELFSHARE_CORE_DLL}")
  install(FILES "${SELFSHARE_CORE_DLL}" DESTINATION "${INSTALL_BUNDLE_LIB_DIR}")
else()
  message(WARNING "selfshare_core.dll missing; run scripts/build_windows.ps1 first")
endif()
