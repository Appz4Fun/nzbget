# Cargo owns dependency tracking (including newly added modules, Cargo.lock,
# build scripts and .cargo/config.toml). Invoke it on every build; a fresh crate
# is a cheap no-op, and consumers relink only when the archive changes.
set(NZBGET_RUST_TARGET "" CACHE STRING "Rust target triple (required for non-macOS cross builds)")
set(RUST_TARGET_EXPLICIT FALSE)
if(NZBGET_RUST_TARGET)
	set(RUST_TARGET_EXPLICIT TRUE)
endif()

# Keep the original implementation for toolchains not yet covered by the port.
# In particular, never link a host Cargo archive into a cross-compiled binary.
if(CMAKE_CROSSCOMPILING AND NOT APPLE AND NOT NZBGET_RUST_TARGET)
	message(STATUS "Cross build without NZBGET_RUST_TARGET: using C++ web encoders")
	return()
endif()

find_program(CARGO cargo HINTS "$ENV{HOME}/.cargo/bin")
find_program(RUSTC rustc HINTS "$ENV{HOME}/.cargo/bin")
if(NOT CARGO OR NOT RUSTC)
	if(RUST_TARGET_EXPLICIT)
		message(FATAL_ERROR "Building the Rust encoders requires cargo and rustc")
	endif()
	message(STATUS "Cargo or rustc unavailable: using C++ web encoders")
	return()
endif()

set(RUST_ENV)
if(APPLE)
	if(NOT NZBGET_RUST_TARGET)
		if(CMAKE_SYSTEM_PROCESSOR MATCHES "^(arm64|aarch64)$")
			set(NZBGET_RUST_TARGET aarch64-apple-darwin)
		elseif(CMAKE_SYSTEM_PROCESSOR STREQUAL "x86_64")
			set(NZBGET_RUST_TARGET x86_64-apple-darwin)
		else()
			message(FATAL_ERROR "Set NZBGET_RUST_TARGET for this macOS architecture")
		endif()
	endif()
	if(CMAKE_OSX_DEPLOYMENT_TARGET)
		list(APPEND RUST_ENV "MACOSX_DEPLOYMENT_TARGET=${CMAKE_OSX_DEPLOYMENT_TARGET}")
	endif()
endif()

if(NOT NZBGET_RUST_TARGET)
	execute_process(COMMAND "${RUSTC}" -vV OUTPUT_VARIABLE RUST_VERSION
		ERROR_VARIABLE RUST_VERSION_ERROR RESULT_VARIABLE RUST_STATUS)
	if(NOT RUST_STATUS EQUAL 0 OR NOT RUST_VERSION MATCHES "host: ([^\r\n]+)")
		message(STATUS "Rust host toolchain unavailable: using C++ web encoders")
		return()
	endif()
	set(NZBGET_RUST_TARGET "${CMAKE_MATCH_1}")
	# A native compiler invoked with -m32 is not a CMake cross build.
	if(CMAKE_SIZEOF_VOID_P EQUAL 4 AND NZBGET_RUST_TARGET MATCHES "^x86_64-")
		string(REGEX REPLACE "^x86_64-" "i686-" NZBGET_RUST_TARGET "${NZBGET_RUST_TARGET}")
	endif()
endif()

# Ask this Rust toolchain for std's native libraries instead of assuming that
# dl alone suffices (notably for older Linux, static linking, and BSD).
file(MAKE_DIRECTORY "${CMAKE_BINARY_DIR}/rust")
file(WRITE "${CMAKE_BINARY_DIR}/rust/native-libs.rs" "// Probe Rust's native link requirements.\n")
execute_process(
	COMMAND "${CMAKE_COMMAND}" -E env ${RUST_ENV} "${RUSTC}"
		--crate-name nzbget_rs_native_libs --crate-type staticlib -C panic=abort
		--target "${NZBGET_RUST_TARGET}" --print native-static-libs
		"${CMAKE_BINARY_DIR}/rust/native-libs.rs" -o "${CMAKE_BINARY_DIR}/rust/native-libs.a"
	RESULT_VARIABLE RUST_STATUS OUTPUT_VARIABLE RUST_NATIVE_OUTPUT ERROR_VARIABLE RUST_NATIVE_ERROR
)
if(NOT RUST_STATUS EQUAL 0)
	if(RUST_TARGET_EXPLICIT)
		message(FATAL_ERROR "Rust target ${NZBGET_RUST_TARGET} is unavailable: ${RUST_NATIVE_ERROR}")
	endif()
	message(STATUS "Rust target ${NZBGET_RUST_TARGET} is unavailable: using C++ web encoders")
	return()
endif()
if(NOT "${RUST_NATIVE_OUTPUT}${RUST_NATIVE_ERROR}" MATCHES "native-static-libs: ([^\r\n]+)")
	message(FATAL_ERROR "Could not determine Rust native link libraries")
endif()
separate_arguments(RUST_NATIVE_LIBS UNIX_COMMAND "${CMAKE_MATCH_1}")

# Separate Cargo directories and imported archives also support multi-config
# generators without requiring generator expressions in OUTPUT/BYPRODUCTS.
if(CMAKE_CONFIGURATION_TYPES)
	set(RUST_CONFIGS ${CMAKE_CONFIGURATION_TYPES})
else()
	set(RUST_CONFIGS ${CMAKE_BUILD_TYPE})
endif()
add_library(nzbget-rs INTERFACE)
foreach(RUST_CONFIG IN LISTS RUST_CONFIGS)
	if(RUST_CONFIG STREQUAL "Debug")
		set(RUST_PROFILE dev)
		set(RUST_PROFILE_DIR debug)
	else()
		set(RUST_PROFILE release)
		set(RUST_PROFILE_DIR release)
	endif()
	set(RUST_TARGET_DIR "${CMAKE_BINARY_DIR}/rust/${RUST_CONFIG}")
	set(RUST_LIB "${RUST_TARGET_DIR}/${NZBGET_RUST_TARGET}/${RUST_PROFILE_DIR}/${CMAKE_STATIC_LIBRARY_PREFIX}nzbget_rs${CMAKE_STATIC_LIBRARY_SUFFIX}")
	add_custom_target(nzbget-rs-build-${RUST_CONFIG}
		COMMAND "${CMAKE_COMMAND}" -E env ${RUST_ENV} "${CARGO}" build --locked
			--profile "${RUST_PROFILE}" --target "${NZBGET_RUST_TARGET}"
			--manifest-path "${CMAKE_SOURCE_DIR}/rust/Cargo.toml" --target-dir "${RUST_TARGET_DIR}"
		BYPRODUCTS "${RUST_LIB}"
		WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}/rust"
		COMMENT "Building nzbget-rs (${RUST_CONFIG})"
		VERBATIM
	)
	add_library(nzbget-rs-lib-${RUST_CONFIG} STATIC IMPORTED)
	set_target_properties(nzbget-rs-lib-${RUST_CONFIG} PROPERTIES IMPORTED_LOCATION "${RUST_LIB}")
	add_dependencies(nzbget-rs-lib-${RUST_CONFIG} nzbget-rs-build-${RUST_CONFIG})
	target_link_libraries(nzbget-rs INTERFACE "$<$<CONFIG:${RUST_CONFIG}>:nzbget-rs-lib-${RUST_CONFIG}>")
endforeach()
target_link_libraries(nzbget-rs INTERFACE ${RUST_NATIVE_LIBS})
target_include_directories(nzbget-rs INTERFACE "${CMAKE_SOURCE_DIR}/rust/include")
target_compile_definitions(nzbget-rs INTERFACE NZBGET_USE_RUST)
list(APPEND LIBS nzbget-rs)
