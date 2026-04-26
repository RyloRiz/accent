// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "ScreenIntentApp",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(name: "ScreenIntentApp", targets: ["ScreenIntentApp"])
    ],
    targets: [
        .executableTarget(
            name: "ScreenIntentApp",
            exclude: ["Info.plist"],
            linkerSettings: [
                .unsafeFlags([
                    "-Xlinker", "-sectcreate",
                    "-Xlinker", "__TEXT",
                    "-Xlinker", "__info_plist",
                    "-Xlinker", "Sources/ScreenIntentApp/Info.plist"
                ])
            ]
        )
    ]
)
