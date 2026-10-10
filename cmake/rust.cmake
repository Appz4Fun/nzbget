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

# Cargo.lock is format 4, which Cargo reads from 1.78 on, and Cargo.toml asks
# for rustc 1.78 (rust-version). Cargo gets the rustc checked here (RUSTC).
foreach(RUST_TOOL CARGO RUSTC)
	execute_process(COMMAND "${${RUST_TOOL}}" --version OUTPUT_VARIABLE RUST_TOOL_VERSION
		ERROR_QUIET RESULT_VARIABLE RUST_TOOL_STATUS)
	if(NOT RUST_TOOL_STATUS EQUAL 0 OR NOT RUST_TOOL_VERSION MATCHES "^[a-z]+ ([0-9]+\\.[0-9]+\\.[0-9]+)"
		OR CMAKE_MATCH_1 VERSION_LESS 1.78)
		if(RUST_TARGET_EXPLICIT)
			message(FATAL_ERROR "Building the Rust encoders requires Cargo and rustc 1.78 or later")
		endif()
		message(STATUS "Cargo or rustc older than 1.78 or unusable: using C++ web encoders")
		return()
	endif()
endforeach()
list(APPEND RUST_ENV "RUSTC=${RUSTC}")

# Ninja Multi-Config before CMake 3.20 can't declare the per-configuration
# archive as an output, so Ninja would stop on a missing input.
if(CMAKE_CONFIGURATION_TYPES AND CMAKE_GENERATOR MATCHES "Ninja" AND CMAKE_VERSION VERSION_LESS 3.20)
	if(RUST_TARGET_EXPLICIT)
		message(FATAL_ERROR "Building the Rust encoders with ${CMAKE_GENERATOR} requires CMake 3.20 or later")
	endif()
	message(STATUS "${CMAKE_GENERATOR} with CMake older than 3.20: using C++ web encoders")
	return()
endif()

# Match the CRT selection to the final C++ link. Without this, GNU targets
# report -lgcc_s even for ENABLE_STATIC, which cannot be linked with -static.
# Pass the same option to the probe and the crate's final staticlib compilation.
set(RUST_CODEGEN_ARGS)
if(ENABLE_STATIC AND NOT CMAKE_CXX_COMPILER_ID STREQUAL "AppleClang")
	list(APPEND RUST_CODEGEN_ARGS -C target-feature=+crt-static)
endif()

# Ask this Rust toolchain for std's native libraries instead of assuming that
# dl alone suffices (notably for older Linux, static linking, and BSD).
file(MAKE_DIRECTORY "${CMAKE_BINARY_DIR}/rust")
file(WRITE "${CMAKE_BINARY_DIR}/rust/native-libs.rs" "// Probe Rust's native link requirements.\n")
execute_process(
	COMMAND "${CMAKE_COMMAND}" -E env ${RUST_ENV} "${RUSTC}"
		--crate-name nzbget_rs_native_libs --crate-type staticlib -C panic=abort
		${RUST_CODEGEN_ARGS}
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

# One Cargo invocation per build, for the active configuration only: Debug uses
# Cargo's dev profile, every other configuration the release profile. Separate
# target directories keep the configurations of multi-config generators apart.
set(RUST_LIB_NAME "${CMAKE_STATIC_LIBRARY_PREFIX}nzbget_rs${CMAKE_STATIC_LIBRARY_SUFFIX}")
if(CMAKE_CONFIGURATION_TYPES)
	set(RUST_CONFIGS ${CMAKE_CONFIGURATION_TYPES})
	set(RUST_CONFIG_DIR "$<CONFIG>")
	set(RUST_PROFILE "$<IF:$<CONFIG:Debug>,dev,release>")
	set(RUST_PROFILE_DIR "$<IF:$<CONFIG:Debug>,debug,release>")
else()
	# Plain paths: CMake before 3.20 takes no generator expressions in BYPRODUCTS,
	# and Ninja needs the archive as a known output.
	set(RUST_CONFIGS ${CMAKE_BUILD_TYPE})
	set(RUST_CONFIG_DIR "${CMAKE_BUILD_TYPE}")
	string(TOUPPER "${CMAKE_BUILD_TYPE}" RUST_BUILD_TYPE_UPPER)
	if(RUST_BUILD_TYPE_UPPER STREQUAL "DEBUG")
		set(RUST_PROFILE dev)
		set(RUST_PROFILE_DIR debug)
	else()
		set(RUST_PROFILE release)
		set(RUST_PROFILE_DIR release)
	endif()
endif()
set(RUST_LIB "${CMAKE_BINARY_DIR}/rust/${RUST_CONFIG_DIR}/${NZBGET_RUST_TARGET}/${RUST_PROFILE_DIR}/${RUST_LIB_NAME}")

# Multi-config Ninja (CMake 3.20 and later, see above) needs the
# per-configuration archive as an output; Visual Studio and Xcode don't.
set(RUST_BYPRODUCTS)
if(NOT CMAKE_CONFIGURATION_TYPES OR CMAKE_GENERATOR MATCHES "Ninja")
	set(RUST_BYPRODUCTS BYPRODUCTS "${RUST_LIB}")
endif()

add_custom_target(nzbget-rs-build
	COMMAND "${CMAKE_COMMAND}" -E env ${RUST_ENV} "${CARGO}" rustc --lib --locked
		--profile "${RUST_PROFILE}" --target "${NZBGET_RUST_TARGET}"
		--manifest-path "${CMAKE_SOURCE_DIR}/rust/Cargo.toml"
		--target-dir "${CMAKE_BINARY_DIR}/rust/${RUST_CONFIG_DIR}"
		-- ${RUST_CODEGEN_ARGS}
	${RUST_BYPRODUCTS}
	WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}/rust"
	COMMENT "Building nzbget-rs"
	VERBATIM
)
add_library(nzbget-rs-lib STATIC IMPORTED)
foreach(RUST_CONFIG IN LISTS RUST_CONFIGS)
	string(TOUPPER "${RUST_CONFIG}" RUST_CONFIG_UPPER)
	if(RUST_CONFIG_UPPER STREQUAL "DEBUG")
		set(RUST_CONFIG_PROFILE_DIR debug)
	else()
		set(RUST_CONFIG_PROFILE_DIR release)
	endif()
	set(RUST_CONFIG_LIB "${CMAKE_BINARY_DIR}/rust/${RUST_CONFIG}/${NZBGET_RUST_TARGET}/${RUST_CONFIG_PROFILE_DIR}/${RUST_LIB_NAME}")
	set_target_properties(nzbget-rs-lib PROPERTIES IMPORTED_LOCATION_${RUST_CONFIG_UPPER} "${RUST_CONFIG_LIB}")
	if(NOT CMAKE_CONFIGURATION_TYPES)
		set_target_properties(nzbget-rs-lib PROPERTIES IMPORTED_LOCATION "${RUST_CONFIG_LIB}")
	endif()
endforeach()
add_dependencies(nzbget-rs-lib nzbget-rs-build)

add_library(nzbget-rs INTERFACE)
target_link_libraries(nzbget-rs INTERFACE nzbget-rs-lib)
target_link_libraries(nzbget-rs INTERFACE ${RUST_NATIVE_LIBS})
target_include_directories(nzbget-rs INTERFACE "${CMAKE_SOURCE_DIR}/rust/include")
target_compile_definitions(nzbget-rs INTERFACE NZBGET_USE_RUST)
list(APPEND LIBS nzbget-rs)
