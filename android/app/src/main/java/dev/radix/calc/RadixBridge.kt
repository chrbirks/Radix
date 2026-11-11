package dev.radix.calc

import com.chaquo.python.PyObject
import com.chaquo.python.Python

/**
 * The only door between Kotlin and the engine. One JSON string in, one out —
 * see `radix.bridge.rpc`. Everything the UI shows is pre-formatted on the
 * Python side; Kotlin never formats a number or touches a bit.
 */
interface RadixBridge {
    fun call(method: String, argsJson: String): String
}

/**
 * Builds the real bridge on first use. The ViewModel factory runs on the main
 * thread, and building a [ChaquopyBridge] there imported the engine, read the
 * state file and loaded the history before the first frame; every call already
 * happens on the bridge dispatcher, so deferring construction moves that work
 * there too.
 */
class LazyBridge(create: () -> RadixBridge) : RadixBridge {
    private val delegate by lazy(create)

    override fun call(method: String, argsJson: String): String = delegate.call(method, argsJson)
}

/** Talks to `radix.bridge.Bridge` through Chaquopy. Python must be started first. */
class ChaquopyBridge(filesDir: String, stateJson: String?) : RadixBridge {
    private val module: PyObject = Python.getInstance().getModule("radix.bridge")
    private val bridge: PyObject = module.callAttr("Bridge", filesDir, stateJson)

    override fun call(method: String, argsJson: String): String =
        module.callAttr("rpc", bridge, method, argsJson).toString()
}
