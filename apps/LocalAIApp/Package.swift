// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "LocalAI",
    platforms: [.macOS(.v15)],
    products: [
        .executable(name: "LocalAI", targets: ["LocalAI"])
    ],
    targets: [
        .executableTarget(
            name: "LocalAI",
            path: "Sources/LocalAI",
            swiftSettings: [.swiftLanguageMode(.v5)]
        )
    ]
)
