var gulp = require('gulp');
const sass = require('gulp-sass')(require('sass'));
postcss = require("gulp-postcss");
autoprefixer = require("autoprefixer");
var sourcemaps = require('gulp-sourcemaps'); 
var browserSync = require('browser-sync').create(); 
cssbeautify = require('gulp-cssbeautify');
var beautify = require('gulp-beautify');


//_______ task for scss folder to css main style 
gulp.task('watch', function() {
	console.log('Command executed successfully compiling SCSS in assets.');
	 return gulp.src('static/assets/scss/**/*.scss') 
		.pipe(sourcemaps.init())                       
		.pipe(sass())
		.pipe(sourcemaps.write(''))  
		.pipe(beautify.css({ indent_size: 4 })) 
		.pipe(gulp.dest('static/assets/css'))
		.pipe(browserSync.reload({
		  stream: true
	}))
})
 
 //_______task for skin-modes
gulp.task('skins', function(){
	console.log('Command executed successfully compiling SKIN-MODES in assets.');
	return gulp.src('static/assets/css/skin-modes.scss')
		 .pipe(sourcemaps.init())
		 .pipe(sass())
		 .pipe(beautify.css({ indent_size: 4 }))
		 .pipe(sourcemaps.write('.'))
		 .pipe(gulp.dest('static/assets/css/'));
		 
 });




