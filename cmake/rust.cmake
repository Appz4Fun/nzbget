# The Rust parts of nzbget (rust/): a static library built by cargo
find_program(CARGO cargo HINTS $ENV{HOME}/.cargo/bin REQUIRED)

set(RUST_TARGET_DIR ${CMAKE_BINARY_DIR}/rust)
set(RUST_LIB ${RUST_TARGET_DIR}/release/${CMAKE_STATIC_LIBRARY_PREFIX}nzbget_rs${CMAKE_STATIC_LIBRARY_SUFFIX})

file(GLOB_RECURSE RUST_SOURCES ${CMAKE_SOURCE_DIR}/rust/src/*.rs)
add_custom_command(
	OUTPUT ${RUST_LIB}
	COMMAND ${CARGO} build --release --manifest-path ${CMAKE_SOURCE_DIR}/rust/Cargo.toml --target-dir ${RUST_TARGET_DIR}
	DEPENDS ${RUST_SOURCES} ${CMAKE_SOURCE_DIR}/rust/Cargo.toml
	COMMENT "Building nzbget-rs (cargo)"
	VERBATIM
)
add_custom_target(nzbget-rs DEPENDS ${RUST_LIB})

set(LIBS ${LIBS} ${RUST_LIB} ${CMAKE_DL_LIBS})
set(INCLUDES ${INCLUDES} ${CMAKE_SOURCE_DIR}/rust/include)
