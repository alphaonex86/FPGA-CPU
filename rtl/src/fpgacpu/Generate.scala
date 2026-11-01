package fpgacpu

import spinal.core._
import vexiiriscv.{ParamSimple, VexiiRiscv}

// Generates the CPU from the VexiiRiscv back end (C0) with this tree's front
// ends: same command line options as vexiiriscv.Generate.
object Generate extends App {
  val param = new ParamSimple()
  assert(new scopt.OptionParser[Unit]("fpgacpu") {
    help("help").text("prints this usage text")
    param.addOptions(this)
  }.parse(args, ()).nonEmpty)

  SpinalConfig().generateVerilog {
    val plugins = param.plugins()
    ParamSimple.setPma(plugins, ParamSimple.defaultPma)
    VexiiRiscv(plugins)
  }
}
